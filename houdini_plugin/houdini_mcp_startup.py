"""Houdini startup script — starts RPyC server for MCP communication.

Loaded via $HOUDINI_USER_PREF_DIR/scripts/456.py (runs after scene load).
Starts an RPyC classic server so the external MCP Server can connect
and control Houdini via conn.modules.hou.

This script ONLY starts the RPyC listener. It does NOT register sessions
or start an MCP server. Session registration happens lazily when an MCP
server (Claude's) actually connects via RPyC.

Behavior is controlled by environment variables and config:
  - HOUDINI_MCP_ENABLED: "1" to start RPyC, "0" to skip.
    If unset, reads ~/houdini_mcp/config.json (human_launch.auto_start_rpyc).
  - HOUDINI_MCP_PORT: specific port number, or "auto" for dynamic allocation.
    If unset, defaults to "auto".

Also installs persistent event monitoring callbacks that record:
  - Node creation / deletion (all contexts: /obj, /stage, /out, /mat, ...)
  - Parameter changes (name + new value)
  - Flag changes (Display, Render, Bypass)
  - Input rewiring / connection changes
  - Node renaming
  - Node selection (network editor)
  - Viewer tool state changes (shelf tools)
  - Hip file save / load / clear

Events are stored in hou.session._mcp_event_log (circular buffer, 2000 entries)
and can be read via the get_event_log MCP tool.

Source of truth — do NOT edit copies in Houdini prefs directory.
"""

import datetime
import json
import os
import socket
import sys
from pathlib import Path

# Paths
MCP_HOME = Path.home() / "houdini_mcp"
CONFIG_FILE = MCP_HOME / "config.json"
LOG_FILE = MCP_HOME / "houdini_startup.log"

# Default port range (must match houdini_mcp/config.py defaults)
_DEFAULT_PORT_RANGE = (18811, 18899)


def _log(msg):
    """Log to both Houdini console and a file for debugging."""
    line = f"[HoudiniMCP] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(str(LOG_FILE), "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat()} {line}\n")
    except Exception:
        pass


def _load_config():
    """Load config from ~/houdini_mcp/config.json, return dict or empty."""
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        _log(f"Failed to read config: {e}")
    return {}


def _get_port_range(config):
    """Get port range from config, with defaults."""
    pr = config.get("port_range", list(_DEFAULT_PORT_RANGE))
    try:
        return (int(pr[0]), int(pr[1]))
    except (IndexError, TypeError, ValueError):
        return _DEFAULT_PORT_RANGE


def _is_port_in_use(port):
    """Check if a TCP port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("localhost", port)) == 0


def _find_free_port(config):
    """Find the next available port in the configured range."""
    min_port, max_port = _get_port_range(config)

    # Read existing sessions to avoid their ports
    sessions_dir = MCP_HOME / "sessions"
    used_ports = set()
    try:
        sessions_dir.mkdir(parents=True, exist_ok=True)
        for f in sessions_dir.glob("*.json"):
            try:
                info = json.loads(f.read_text(encoding="utf-8"))
                if "port" in info:
                    used_ports.add(int(info["port"]))
            except Exception:
                pass
    except Exception:
        pass

    for port in range(min_port, max_port + 1):
        if port in used_ports:
            continue
        if not _is_port_in_use(port):
            return port

    raise RuntimeError(f"No available ports in range {min_port}-{max_port}")


def _should_start(config):
    """Determine whether to start RPyC based on env vars and config.

    Priority:
      1. HOUDINI_MCP_ENABLED env var ("1" → yes, "0" → no)
      2. Config: human_launch.auto_start_rpyc (default: False)
    """
    env_enabled = os.environ.get("HOUDINI_MCP_ENABLED")
    if env_enabled is not None:
        return env_enabled.strip() == "1"
    # No env var — check config (default: human launch does NOT start)
    return config.get("human_launch", {}).get("auto_start_rpyc", False)


def _resolve_port(config):
    """Determine which port to use.

    Priority:
      1. HOUDINI_MCP_PORT env var (numeric → use that port, "auto" → find free)
      2. Default: auto-find free port
    """
    env_port = os.environ.get("HOUDINI_MCP_PORT", "").strip()
    if env_port and env_port != "auto":
        try:
            return int(env_port)
        except ValueError:
            _log(f"Invalid HOUDINI_MCP_PORT '{env_port}', falling back to auto")
    return _find_free_port(config)



def start_rpyc_server():
    """Start the RPyC server for MCP communication."""
    _log(f"Startup script executing (Python {sys.version})")

    config = _load_config()

    if not _should_start(config):
        _log("MCP RPyC server disabled (HOUDINI_MCP_ENABLED=0 or config)")
        return

    port = _resolve_port(config)

    if _is_port_in_use(port):
        _log(f"RPyC port {port} already in use, skipping.")
        return

    try:
        import hrpyc
        _log(f"hrpyc module found: {hrpyc.__file__}")
        hrpyc.start_server(port=port)
        _log(f"RPyC server started on port {port}")
    except ImportError as e:
        _log(f"hrpyc not available: {e}")
        try:
            import rpyc
            from rpyc.utils.server import ThreadedServer
            from rpyc.core.service import SlaveService
            server = ThreadedServer(
                SlaveService,
                hostname="localhost",
                port=port,
                reuse_addr=True,
            )
            import threading
            t = threading.Thread(target=server.start, daemon=True)
            t.start()
            _log(f"RPyC server started via rpyc fallback on port {port}")
        except Exception as e2:
            _log(f"Both hrpyc and rpyc fallback failed: {e2}")
            return
    except Exception as e:
        _log(f"Failed to start RPyC server: {e}")
        return

    # Store port on hou.session for MCP tools to read when they connect
    try:
        import hou
        hou.session._mcp_port = port
    except Exception:
        pass


def install_event_monitoring():
    """Install persistent event callbacks inside the Houdini process.

    Records node/parameter/selection/viewer/hipfile events into a circular
    buffer at hou.session._mcp_event_log, readable via get_event_log MCP tool.
    Safe to call multiple times — idempotent.
    """
    try:
        import hou
        import time
        import threading

        _MAX_ENTRIES = 2000

        # ── Initialise shared state (idempotent) ──────────────────────────
        if not hasattr(hou.session, "_mcp_event_log"):
            hou.session._mcp_event_log = []
            hou.session._mcp_event_lock = threading.Lock()
            hou.session._mcp_event_listeners = {}
            hou.session._mcp_event_enabled = False

        def _elog(entry):
            entry["time"] = time.time()
            entry["time_str"] = time.strftime("%H:%M:%S", time.localtime(entry["time"]))
            with hou.session._mcp_event_lock:
                buf = hou.session._mcp_event_log
                buf.append(entry)
                if len(buf) > _MAX_ENTRIES:
                    del buf[:len(buf) - _MAX_ENTRIES]

        # ── Node callback factories ───────────────────────────────────────
        def _make_child_cb(parent_path):
            def _cb(event_type, **kwargs):
                child = kwargs.get("child_node")
                if event_type == hou.nodeEventType.ChildCreated and child is not None:
                    _elog({
                        "event": "node_created",
                        "parent": parent_path,
                        "node": child.path(),
                        "type": child.type().name(),
                    })
                    _subscribe_node(child)
                elif event_type == hou.nodeEventType.ChildDeleted and child is not None:
                    _elog({"event": "node_deleted", "parent": parent_path, "node": child.path()})
            return _cb

        def _make_node_cb(node_path):
            def _cb(event_type, **kwargs):
                if event_type == hou.nodeEventType.ParmTupleChanged:
                    pt = kwargs.get("parm_tuple")
                    if pt is not None:
                        try:
                            name = pt.name()
                            val = tuple(p.eval() for p in pt)
                            val = val[0] if len(val) == 1 else val
                            _elog({"event": "parm_changed", "node": node_path,
                                   "parm": name, "value": str(val)})
                        except Exception:
                            _elog({"event": "parm_changed", "node": node_path, "parm": "?"})
                elif event_type == hou.nodeEventType.FlagChanged:
                    _elog({"event": "flag_changed", "node": node_path})
                elif event_type == hou.nodeEventType.NameChanged:
                    node = kwargs.get("node")
                    _elog({"event": "name_changed", "node": node_path,
                           "new_name": node.name() if node else "?"})
                elif event_type == hou.nodeEventType.InputRewired:
                    _elog({"event": "input_rewired", "node": node_path,
                           "input_index": kwargs.get("input_index", -1)})
            return _cb

        _CHILD_EVENTS = (hou.nodeEventType.ChildCreated, hou.nodeEventType.ChildDeleted)
        _NODE_EVENTS = (
            hou.nodeEventType.ParmTupleChanged,
            hou.nodeEventType.FlagChanged,
            hou.nodeEventType.NameChanged,
            hou.nodeEventType.InputRewired,
        )

        def _subscribe_node(node):
            path = node.path()
            if path in hou.session._mcp_event_listeners:
                return
            cbs = []
            try:
                if node.isNetwork():
                    cb = _make_child_cb(path)
                    node.addEventCallback(_CHILD_EVENTS, cb)
                    cbs.append(("child", cb))
            except Exception:
                pass
            try:
                cb = _make_node_cb(path)
                node.addEventCallback(_NODE_EVENTS, cb)
                cbs.append(("node", cb))
            except Exception:
                pass
            hou.session._mcp_event_listeners[path] = cbs

        def _subscribe_tree(node, depth=0):
            if depth > 20:
                return
            _subscribe_node(node)
            try:
                for child in node.children():
                    _subscribe_tree(child, depth + 1)
            except Exception:
                pass

        # ── Subscribe to all context trees ───────────────────────────────
        root = hou.node("/")
        if root is not None:
            _subscribe_node(root)
        for ctx in ["/obj", "/stage", "/out", "/shop", "/mat", "/img", "/ch", "/tasks"]:
            n = hou.node(ctx)
            if n is not None:
                _subscribe_tree(n)

        # ── Selection callback ────────────────────────────────────────────
        if "_mcp_sel_cb" not in hou.session.__dict__:
            def _sel_cb(selection):
                try:
                    paths = [n.path() for n in selection if hasattr(n, "path")]
                except Exception:
                    paths = []
                if paths:
                    _elog({"event": "nodes_selected", "nodes": paths})
            hou.session._mcp_sel_cb = _sel_cb
            hou.ui.addSelectionCallback(_sel_cb)

        # ── SceneViewer state callback ────────────────────────────────────
        if "_mcp_viewer_cb" not in hou.session.__dict__:
            viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
            if viewer is not None:
                def _viewer_cb(event_type, **kwargs):
                    evt_str = str(event_type).replace("sceneViewerEvent.", "")
                    if evt_str in ("StateEntered", "StateExited",
                                   "StateInterrupted", "StateResumed"):
                        _elog({"event": "viewer_state", "state": evt_str,
                               "tool": kwargs.get("state_name", "")})
                hou.session._mcp_viewer_cb = _viewer_cb
                viewer.addEventCallback(_viewer_cb)

        # ── HipFile callback ──────────────────────────────────────────────
        if "_mcp_hip_cb" not in hou.session.__dict__:
            def _hip_cb(event_type):
                evt_str = str(event_type).replace("hipFileEventType.", "")
                try:
                    path = hou.hipFile.path()
                except Exception:
                    path = ""
                _elog({"event": "hip_file", "action": evt_str, "path": path})
            hou.session._mcp_hip_cb = _hip_cb
            hou.hipFile.addEventCallback(_hip_cb)

        hou.session._mcp_event_enabled = True
        _elog({"event": "monitoring_started",
               "subscribed_nodes": len(hou.session._mcp_event_listeners)})
        _log(f"Event monitoring active ({len(hou.session._mcp_event_listeners)} nodes subscribed)")

    except Exception as e:
        _log(f"Event monitoring install failed (non-fatal): {e}")


# Guard: only run once per Houdini session (prevents double execution
# if old copies of 123.py/pythonrc.py still exist alongside the new hook)
import builtins as _builtins
if not getattr(_builtins, "_houdini_mcp_started", False):
    _builtins._houdini_mcp_started = True

    try:
        start_rpyc_server()
    except Exception as e:
        _log(f"Startup error (non-fatal): {e}")

    # Delay event monitoring until UI is ready.
    # 456.py runs before desktops/viewers are available, so we defer
    # via hdefereval which executes on the next UI idle tick.
    try:
        import hdefereval
        hdefereval.executeDeferred(install_event_monitoring)
        _log("Event monitoring deferred until UI is ready")
    except ImportError:
        # hdefereval not available (e.g. hython CLI) — try directly
        try:
            install_event_monitoring()
        except Exception as e:
            _log(f"Event monitoring error (non-fatal): {e}")
else:
    _log("Startup script already executed this session, skipping.")
