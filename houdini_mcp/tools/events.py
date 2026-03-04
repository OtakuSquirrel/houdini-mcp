"""Event monitoring tools — track node/parameter changes across all contexts.

Houdini (unlike Maya) does not echo every UI operation as a command.
This module installs persistent event callbacks inside the Houdini process
that record node creation, deletion, parameter changes, flag changes,
connection rewiring, renaming, node selection, viewer tool state changes,
and hip file save/load events.  The log is stored in a circular buffer
in-process and can be retrieved (and optionally cleared) via MCP tools.

Note on viewport camera navigation (rotate/pan/zoom): Houdini does not
expose Python callbacks for camera navigation — it is handled entirely in
C++.  These operations cannot be captured even with polling.
"""

from __future__ import annotations

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain

# ---------------------------------------------------------------------------
# Remote code executed inside Houdini
# ---------------------------------------------------------------------------

_INSTALL_CODE = r'''
import hou, time, threading

# ── Circular buffer ────────────────────────────────────────────────────────
_MAX_ENTRIES = 2000

if not hasattr(hou.session, "_mcp_event_log"):
    hou.session._mcp_event_log = []
    hou.session._mcp_event_lock = threading.Lock()
    hou.session._mcp_event_listeners = {}   # node_path -> callback
    hou.session._mcp_event_enabled = False

def _log(entry: dict):
    entry["time"] = time.time()
    entry["time_str"] = time.strftime("%H:%M:%S", time.localtime(entry["time"]))
    with hou.session._mcp_event_lock:
        buf = hou.session._mcp_event_log
        buf.append(entry)
        if len(buf) > _MAX_ENTRIES:
            del buf[:len(buf) - _MAX_ENTRIES]

# ── Callback factory ──────────────────────────────────────────────────────
def _make_child_cb(parent_path):
    """Return a callback for ChildCreated / ChildDeleted on *parent_path*."""
    def _cb(event_type, **kwargs):
        child = kwargs.get("child_node")
        if event_type == hou.nodeEventType.ChildCreated:
            if child is not None:
                _log({
                    "event": "node_created",
                    "parent": parent_path,
                    "node": child.path(),
                    "type": child.type().name(),
                })
                # Auto-subscribe the new child so we see *its* parm changes too
                _subscribe_node(child)
        elif event_type == hou.nodeEventType.ChildDeleted:
            if child is not None:
                _log({
                    "event": "node_deleted",
                    "parent": parent_path,
                    "node": child.path(),
                })
    return _cb

def _make_node_cb(node_path):
    """Return a callback for per-node events (parm change, flag, rename, input)."""
    def _cb(event_type, **kwargs):
        if event_type == hou.nodeEventType.ParmTupleChanged:
            pt = kwargs.get("parm_tuple")
            if pt is not None:
                try:
                    name = pt.name()
                    # Read value – handle tuples vs single
                    val = tuple(p.eval() for p in pt)
                    if len(val) == 1:
                        val = val[0]
                    _log({
                        "event": "parm_changed",
                        "node": node_path,
                        "parm": name,
                        "value": str(val),
                    })
                except Exception:
                    _log({"event": "parm_changed", "node": node_path, "parm": "?"})

        elif event_type == hou.nodeEventType.FlagChanged:
            _log({"event": "flag_changed", "node": node_path})

        elif event_type == hou.nodeEventType.NameChanged:
            node = kwargs.get("node")
            new_name = node.name() if node else "?"
            _log({"event": "name_changed", "node": node_path, "new_name": new_name})

        elif event_type == hou.nodeEventType.InputRewired:
            idx = kwargs.get("input_index", -1)
            _log({"event": "input_rewired", "node": node_path, "input_index": idx})
    return _cb

# ── Subscription management ───────────────────────────────────────────────
_CHILD_EVENTS = (
    hou.nodeEventType.ChildCreated,
    hou.nodeEventType.ChildDeleted,
)

_NODE_EVENTS = (
    hou.nodeEventType.ParmTupleChanged,
    hou.nodeEventType.FlagChanged,
    hou.nodeEventType.NameChanged,
    hou.nodeEventType.InputRewired,
)

def _subscribe_node(node):
    """Subscribe to events on a single node (idempotent)."""
    path = node.path()
    if path in hou.session._mcp_event_listeners:
        return
    cbs = []
    # Children events (if the node is a network)
    try:
        if node.isNetwork():
            cb = _make_child_cb(path)
            node.addEventCallback(_CHILD_EVENTS, cb)
            cbs.append(("child", cb))
    except Exception:
        pass
    # Per-node events
    try:
        cb = _make_node_cb(path)
        node.addEventCallback(_NODE_EVENTS, cb)
        cbs.append(("node", cb))
    except Exception:
        pass
    hou.session._mcp_event_listeners[path] = cbs

def _subscribe_tree(node, depth=0, max_depth=20):
    """Recursively subscribe to *node* and all its descendants."""
    if depth > max_depth:
        return
    _subscribe_node(node)
    try:
        for child in node.children():
            _subscribe_tree(child, depth + 1, max_depth)
    except Exception:
        pass

# ── Selection callback ────────────────────────────────────────────────────
def _selection_cb(selection):
    """Called when the user selects nodes in the network editor."""
    try:
        paths = [n.path() for n in selection if hasattr(n, "path")]
    except Exception:
        paths = []
    if paths:
        _log({"event": "nodes_selected", "nodes": paths})

# ── SceneViewer state callback ────────────────────────────────────────────
def _make_viewer_cb():
    """Return a callback for SceneViewer state changes (tool activation etc.)."""
    def _cb(event_type, **kwargs):
        state_name = kwargs.get("state_name", "")
        evt_str = str(event_type).replace("sceneViewerEvent.", "")
        if evt_str in ("StateEntered", "StateExited", "StateInterrupted", "StateResumed"):
            _log({"event": "viewer_state", "state": evt_str, "tool": state_name})
    return _cb

# ── HipFile callback ──────────────────────────────────────────────────────
def _hip_cb(event_type):
    """Called on hip file save / load / clear events."""
    evt_str = str(event_type).replace("hipFileEventType.", "")
    try:
        path = hou.hipFile.path()
    except Exception:
        path = ""
    _log({"event": "hip_file", "action": evt_str, "path": path})

# ── Top-level installer ───────────────────────────────────────────────────
def install():
    """Walk every context root and subscribe to the full tree."""
    roots = []
    for path in ["/obj", "/stage", "/out", "/shop", "/mat", "/img", "/ch", "/tasks"]:
        n = hou.node(path)
        if n is not None:
            roots.append(n)
    # Also subscribe to "/" for top-level child events
    root = hou.node("/")
    if root is not None:
        _subscribe_node(root)

    for r in roots:
        _subscribe_tree(r)

    # ── Selection callback (idempotent guard) ──────────────────────────────
    if "_mcp_sel_cb" not in hou.session.__dict__:
        hou.session._mcp_sel_cb = _selection_cb
        hou.ui.addSelectionCallback(_selection_cb)

    # ── SceneViewer callback ───────────────────────────────────────────────
    if "_mcp_viewer_cb" not in hou.session.__dict__:
        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if viewer is not None:
            cb = _make_viewer_cb()
            hou.session._mcp_viewer_cb = cb
            viewer.addEventCallback(cb)

    # ── HipFile callback ───────────────────────────────────────────────────
    if "_mcp_hip_cb" not in hou.session.__dict__:
        hou.session._mcp_hip_cb = _hip_cb
        hou.hipFile.addEventCallback(_hip_cb)

    hou.session._mcp_event_enabled = True
    _log({"event": "monitoring_started", "subscribed_nodes": len(hou.session._mcp_event_listeners)})
    return len(hou.session._mcp_event_listeners)

install()
'''

_GET_LOG_CODE = r'''
import hou, threading
result = []
if hasattr(hou.session, "_mcp_event_log"):
    with hou.session._mcp_event_lock:
        result = list(hou.session._mcp_event_log[__OFFSET__:])
len(result)
'''

_GET_LOG_AND_CLEAR_CODE = r'''
import hou, threading
result = []
if hasattr(hou.session, "_mcp_event_log"):
    with hou.session._mcp_event_lock:
        result = list(hou.session._mcp_event_log)
        hou.session._mcp_event_log.clear()
len(result)
'''

_GET_STATUS_CODE = r'''
import hou
status = {
    "enabled": getattr(hou.session, "_mcp_event_enabled", False),
    "log_size": len(getattr(hou.session, "_mcp_event_log", [])),
    "subscribed_nodes": len(getattr(hou.session, "_mcp_event_listeners", {})),
}
status
'''

_STOP_CODE = r'''
import hou
removed = 0

# Node event callbacks
if hasattr(hou.session, "_mcp_event_listeners"):
    for path, cbs in list(hou.session._mcp_event_listeners.items()):
        node = hou.node(path)
        if node is not None:
            for kind, cb in cbs:
                try:
                    node.removeEventCallback(cb)
                    removed += 1
                except Exception:
                    pass
    hou.session._mcp_event_listeners.clear()

# Selection callback
if hasattr(hou.session, "_mcp_sel_cb"):
    try:
        hou.ui.removeSelectionCallback(hou.session._mcp_sel_cb)
        removed += 1
    except Exception:
        pass
    del hou.session._mcp_sel_cb

# SceneViewer callback
if hasattr(hou.session, "_mcp_viewer_cb"):
    try:
        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if viewer is not None:
            viewer.removeEventCallback(hou.session._mcp_viewer_cb)
            removed += 1
    except Exception:
        pass
    del hou.session._mcp_viewer_cb

# HipFile callback
if hasattr(hou.session, "_mcp_hip_cb"):
    try:
        hou.hipFile.removeEventCallback(hou.session._mcp_hip_cb)
        removed += 1
    except Exception:
        pass
    del hou.session._mcp_hip_cb

hou.session._mcp_event_enabled = False
removed
'''


# ---------------------------------------------------------------------------
# Helper: execute code in Houdini and return result
# ---------------------------------------------------------------------------

def _remote_exec(code: str) -> dict:
    """Execute Python code in Houdini, return dict with stdout/return_value/error."""
    conn = houdini.conn
    remote_sys = conn.modules.sys
    remote_io = conn.modules.io

    old_stdout = remote_sys.stdout
    captured = remote_io.StringIO()
    remote_sys.stdout = captured

    error = None
    return_value = None
    try:
        ns = conn.modules.builtins.dict()
        ns["hou"] = conn.modules.hou
        conn.modules.builtins.exec(code, ns)
        # Try evaluating last expression
        lines = code.strip().split("\n")
        if lines:
            last = lines[-1].strip()
            if last and not last.startswith(("import ", "from ", "def ", "class ",
                                             "if ", "for ", "while ", "with ",
                                             "try:", "except", "#", "hou.session")):
                try:
                    return_value = obtain(conn.modules.builtins.eval(last, ns))
                except Exception:
                    pass
    except Exception as e:
        error = str(e)
    finally:
        remote_sys.stdout = old_stdout

    result = {"stdout": obtain(captured.getvalue())}
    if return_value is not None:
        result["return_value"] = return_value
    if error:
        result["error"] = error
    return result


def _remote_get_log(offset: int = 0, clear: bool = False) -> list[dict]:
    """Retrieve log entries from Houdini's in-process buffer."""
    conn = houdini.conn
    ns = conn.modules.builtins.dict()
    ns["hou"] = conn.modules.hou

    if clear:
        code = _GET_LOG_AND_CLEAR_CODE
    else:
        code = _GET_LOG_CODE.replace("__OFFSET__", str(offset))

    conn.modules.builtins.exec(code, ns)
    remote_result = ns.get("result", [])

    # Convert each entry from RPyC netref to native dict
    entries = []
    try:
        for entry in remote_result:
            native = {}
            for k in entry:
                native[obtain(k)] = obtain(entry[k])
            entries.append(native)
    except Exception:
        pass
    return entries


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def start_event_monitoring() -> dict:
    """Install event listeners on ALL Houdini contexts (/obj, /stage, /out, etc.).

    Monitors: node creation, deletion, parameter changes, flag changes,
    connection rewiring, and renaming.  Events are stored in a circular buffer
    (max 2000 entries) inside the Houdini process.

    Safe to call multiple times — idempotent.

    Returns:
        Dict with subscribed node count and status.
    """
    result = _remote_exec(_INSTALL_CODE)
    if result.get("error"):
        return {"status": "error", "error": result["error"]}

    status = _remote_exec(_GET_STATUS_CODE)
    return {
        "status": "monitoring_active",
        "subscribed_nodes": status.get("return_value", {}).get("subscribed_nodes", 0),
        "buffer_max": 2000,
    }


@mcp.tool()
def stop_event_monitoring() -> dict:
    """Remove all event listeners and stop monitoring.

    The existing log buffer is preserved and can still be read.

    Returns:
        Dict with number of callbacks removed.
    """
    result = _remote_exec(_STOP_CODE)
    removed = result.get("return_value", 0)
    return {"status": "stopped", "callbacks_removed": removed}


@mcp.tool()
def get_event_log(last_n: int = 50, clear: bool = False) -> dict:
    """Retrieve recent Houdini operation events.

    Like Maya's Script Editor command echo, but for Houdini.
    Returns node creations, deletions, parameter changes, flag changes,
    connection changes, and renames.

    Args:
        last_n: Number of most recent entries to return (default 50, max 2000).
        clear: If True, clear the buffer after reading.

    Returns:
        Dict with event entries and total count.
    """
    if clear:
        entries = _remote_get_log(clear=True)
    else:
        entries = _remote_get_log(offset=0)

    total = len(entries)
    # Return only the last N
    if last_n > 0 and total > last_n:
        entries = entries[-last_n:]

    return {
        "total_in_buffer": total,
        "returned": len(entries),
        "events": entries,
    }


@mcp.tool()
def get_event_monitoring_status() -> dict:
    """Check if event monitoring is active and how many events are buffered.

    Returns:
        Dict with enabled flag, log size, and subscribed node count.
    """
    result = _remote_exec(_GET_STATUS_CODE)
    if result.get("error"):
        return {"enabled": False, "error": result["error"]}
    return result.get("return_value", {"enabled": False})
