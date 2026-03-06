"""Houdini lifecycle tools — start, stop, status, setup.

Allows the Agent to launch and manage the Houdini process autonomously.
No human intervention needed.

Supports two modes:
- hython (default): Headless Python mode. Always reliable, no GUI dialogs.
- gui: Full Houdini GUI. Requires startup scripts installed (use install_startup_scripts).

Multi-version support: Houdini 20.5+ (auto-detected from install directory).
Multi-instance support: Dynamic port allocation via session registry.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

from houdini_mcp.server import mcp, houdini, set_port, get_session_id
from houdini_mcp import registry

# Process tracking now handled by ConnectionManager (houdini._processes)

# Startup script source (single source of truth)
_PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "houdini_plugin"
_STARTUP_SCRIPT = _PLUGIN_DIR / "houdini_mcp_startup.py"


def _find_houdini_installations() -> list[dict]:
    """Discover installed Houdini versions from configured search paths."""
    from houdini_mcp.config import get_houdini_search_paths

    results = []
    seen_versions: set[str] = set()
    for search_path_str in get_houdini_search_paths():
        search_root = Path(search_path_str)
        if not search_root.exists():
            continue
        for d in sorted(search_root.iterdir(), reverse=True):
            if d.name.startswith("Houdini ") and d.is_dir():
                version = d.name.replace("Houdini ", "")
                if version in seen_versions:
                    continue
                hython = d / "bin" / "hython.exe"
                gui_exe = d / "bin" / "houdinifx.exe"
                if not gui_exe.exists():
                    gui_exe = d / "bin" / "houdini.exe"
                entry = {
                    "version": version,
                    "dir": str(d),
                }
                if gui_exe.exists():
                    entry["gui_exe"] = str(gui_exe)
                if hython.exists():
                    entry["hython"] = str(hython)
                if gui_exe.exists() or hython.exists():
                    seen_versions.add(version)
                    results.append(entry)
    return results


def _get_houdini_prefs_dir(version: str) -> Path:
    """Get the Houdini user prefs directory for a given version.

    On Windows, Houdini sets $HOME to ~/Documents, so prefs live at
    ~/Documents/houdiniX.Y/ (e.g. C:/Users/otaku/Documents/houdini21.0/).

    The version string may include a patch number (e.g. '21.0.551'),
    but the prefs dir only uses major.minor (e.g. 'houdini21.0').
    """
    # Extract major.minor from version string like '21.0.551' or '20.5'
    match = re.match(r"(\d+\.\d+)", version)
    if not match:
        raise ValueError(f"Cannot parse Houdini version: {version}")
    major_minor = match.group(1)

    if os.name == "nt":
        return Path.home() / "Documents" / f"houdini{major_minor}"
    else:
        return Path.home() / f"houdini{major_minor}"


def _is_port_open(port: int, host: str = "localhost") -> bool:
    """Check if the RPyC port is accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


# Hook line injected into 456.py — must be a single, self-contained line
_HOOK_TAG = "# [HoudiniMCP]"
_HOOK_LINE = (
    'exec(open(hou.homeHoudiniDirectory() + "/scripts/houdini_mcp_startup.py").read())'
    f'  {_HOOK_TAG}'
)


def _inject_hook(target_file: Path) -> str:
    """Append our hook line to a script file if not already present.

    Non-destructive: preserves all existing content. Idempotent.
    Returns 'injected', 'already_present', or 'created'.
    """
    if target_file.exists():
        content = target_file.read_text(encoding="utf-8")
        if _HOOK_TAG in content:
            return "already_present"
        # Append our hook at the end
        if not content.endswith("\n"):
            content += "\n"
        content += f"\n{_HOOK_LINE}\n"
        target_file.write_text(content, encoding="utf-8")
        return "injected"
    else:
        target_file.write_text(f"{_HOOK_LINE}\n", encoding="utf-8")
        return "created"


def _remove_hook(target_file: Path) -> str:
    """Remove our hook line from a script file.

    Returns 'removed', 'not_found', or 'file_missing'.
    """
    if not target_file.exists():
        return "file_missing"
    content = target_file.read_text(encoding="utf-8")
    if _HOOK_TAG not in content:
        return "not_found"
    # Remove lines containing our tag
    lines = [line for line in content.splitlines() if _HOOK_TAG not in line]
    # Remove trailing blank lines left behind
    while lines and lines[-1].strip() == "":
        lines.pop()
    target_file.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    return "removed"


@mcp.tool()
def install_startup_scripts(version: str | None = None) -> dict:
    """Install MCP startup hook into a Houdini version's scripts directory.

    Non-destructive: copies our startup script as a separate file
    (houdini_mcp_startup.py) and injects a one-line hook into 456.py.
    Existing content in 456.py is fully preserved.

    Only hooks into 456.py (runs once after scene load) to avoid
    multiple executions.

    Safe to run multiple times (idempotent).

    Args:
        version: Houdini version to install for (e.g. '20.5', '21.0.551').
                 If None, installs for ALL detected Houdini versions.

    Returns:
        Dict with installation results per version.
    """
    if not _STARTUP_SCRIPT.exists():
        raise FileNotFoundError(
            f"Startup script not found: {_STARTUP_SCRIPT}. "
            "Ensure houdini_plugin/houdini_mcp_startup.py exists."
        )

    installations = _find_houdini_installations()
    if not installations:
        raise RuntimeError(
            "No Houdini installations found. "
            "Configure search paths in WebUI or install Houdini."
        )

    if version is not None:
        targets = [i for i in installations if i["version"].startswith(version)]
        if not targets:
            available = [i["version"] for i in installations]
            raise ValueError(
                f"Houdini version '{version}' not found. Available: {available}"
            )
    else:
        targets = installations

    results = {}

    for inst in targets:
        ver = inst["version"]
        prefs_dir = _get_houdini_prefs_dir(ver)
        scripts_dir = prefs_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copy our startup script as a separate file
        dest_script = scripts_dir / "houdini_mcp_startup.py"
        shutil.copy2(str(_STARTUP_SCRIPT), str(dest_script))

        # 2. Inject hook into 456.py only (non-destructive)
        hook_file = scripts_dir / "456.py"
        hook_status = _inject_hook(hook_file)

        results[ver] = {
            "scripts_dir": str(scripts_dir),
            "startup_script": str(dest_script),
            "hook_file": str(hook_file),
            "hook_status": hook_status,
        }

    return {
        "status": "installed",
        "versions": results,
        "source": str(_STARTUP_SCRIPT),
    }


@mcp.tool()
def uninstall_startup_scripts(version: str) -> dict:
    """Remove MCP startup hook from a Houdini version's scripts directory.

    Removes the hook line from 456.py (preserving other content) and
    deletes houdini_mcp_startup.py.

    Args:
        version: Houdini version to uninstall from (e.g. '20.5', '21.0').

    Returns:
        Dict with uninstallation results.
    """
    prefs_dir = _get_houdini_prefs_dir(version)
    scripts_dir = prefs_dir / "scripts"

    removed = []

    # 1. Remove hook from 456.py
    hook_file = scripts_dir / "456.py"
    hook_status = _remove_hook(hook_file)

    # 2. Delete our startup script
    startup_file = scripts_dir / "houdini_mcp_startup.py"
    if startup_file.exists():
        startup_file.unlink()
        removed.append(str(startup_file))

    return {
        "status": "uninstalled",
        "version": version,
        "hook_status": hook_status,
        "removed_files": removed,
    }


@mcp.tool()
def get_houdini_status() -> dict:
    """Check if Houdini is running and the RPyC server is reachable.

    If Houdini was just launched, rpyc_reachable may be False for up to
    90 seconds while Houdini initializes. This is normal for GUI mode.

    Returns:
        Dict with process status, RPyC connectivity, installed versions,
        and session info.
    """
    rpyc_reachable = _is_port_open(houdini.port)

    proc = houdini.get_process()
    process_alive = False
    process_pid = None
    if proc is not None:
        poll = proc.poll()
        if poll is None:
            process_alive = True
            process_pid = proc.pid
        else:
            houdini.unregister_process(houdini._active_port)

    connected = houdini.is_connected()
    installations = _find_houdini_installations()

    return {
        "rpyc_reachable": rpyc_reachable,
        "rpyc_port": houdini.port,
        "session_id": get_session_id(),
        "managed_process_alive": process_alive,
        "managed_process_pid": process_pid,
        "mcp_connected": connected,
        "installed_versions": installations,
        "connections": houdini.list_connections(),
    }


@mcp.tool()
def start_houdini(
    version: str | None = None,
    mode: str = "gui",
    wait_for_rpyc: bool = True,
    timeout: int = 120,
    open_file: str | None = None,
    port: int | None = None,
) -> dict:
    """Launch Houdini and wait for it to be ready for MCP communication.

    IMPORTANT: Houdini GUI takes 30-90 seconds to fully start up and
    initialize the RPyC server. This is normal — do NOT assume failure
    if this tool takes a while. The tool will keep retrying the connection
    automatically until the timeout is reached.

    Automatically allocates a free port to avoid conflicts with other instances.
    Sets HOUDINI_MCP_ENABLED=1 and HOUDINI_MCP_PORT so the startup script
    starts RPyC on the correct port.

    Args:
        version: Houdini version to launch (e.g. '21.0.551'). If None, uses latest.
        mode: 'hython' (headless, reliable) or 'gui' (full UI, needs 456.py).
        wait_for_rpyc: Whether to wait until the RPyC server is reachable (default True).
        timeout: Max seconds to wait for RPyC server (default 120).
                 GUI mode typically needs 60-90s. Do not lower this.
        open_file: Optional .hip file path to open on launch (gui mode only).
        port: Specific RPyC port to use. If None, auto-allocates a free port.

    Returns:
        Dict with process PID, port, session ID, and connection status.
    """
    # Allocate port
    if port is None:
        port = registry.allocate_port()

    # Check if already running on this port
    if _is_port_open(port):
        try:
            houdini.connect(port=port)
            return {
                "status": "already_running",
                "rpyc_connected": True,
                "port": port,
                "session_id": get_session_id(),
                "message": f"Houdini RPyC server already reachable on port {port}, connected.",
            }
        except Exception:
            pass

    # Find the right executable
    installations = _find_houdini_installations()
    if not installations:
        raise RuntimeError(
            "No Houdini installation found. "
            "Configure search paths in WebUI or install Houdini."
        )

    inst = None
    if version is not None:
        for i in installations:
            if i["version"] == version or i["version"].startswith(version):
                inst = i
                break
        if inst is None:
            available = [i["version"] for i in installations]
            raise ValueError(
                f"Houdini version {version} not found. Available: {available}"
            )
    else:
        inst = installations[0]  # Latest version
        version = inst["version"]

    # Environment variables for the startup script
    env = os.environ.copy()
    env["HOUDINI_MCP_ENABLED"] = "1"
    env["HOUDINI_MCP_PORT"] = str(port)

    if mode == "hython":
        hython_path = inst.get("hython")
        if not hython_path:
            raise RuntimeError(f"hython.exe not found for Houdini {version}")

        # Launch hython with RPyC server inline
        script = (
            "import hrpyc, time, sys; "
            f"hrpyc.start_server(port={port}); "
            f"print('[HoudiniMCP] RPyC server started on port {port}', flush=True); "
            "[time.sleep(1) for _ in iter(int,1)]"
        )
        proc = subprocess.Popen(
            [hython_path, "-c", script],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        # GUI mode — ensure startup scripts are installed for this version
        gui_exe = inst.get("gui_exe")
        if not gui_exe:
            raise RuntimeError(f"houdinifx.exe not found for Houdini {version}")

        # Auto-install startup scripts if not already present
        try:
            prefs_dir = _get_houdini_prefs_dir(version)
            scripts_dir = prefs_dir / "scripts"
            if not (scripts_dir / "456.py").exists():
                install_startup_scripts(version=version)
        except Exception:
            pass  # Non-fatal — user may have installed manually

        cmd = [gui_exe]
        if open_file:
            cmd.append(open_file)
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    # Track this process as owned by this MCP server
    houdini.register_process(port, proc)

    # Set the port so connect() targets this Houdini instance
    set_port(port)

    result = {
        "status": "launched",
        "version": version,
        "mode": mode,
        "pid": proc.pid,
        "port": port,
    }

    if not wait_for_rpyc:
        result["rpyc_connected"] = False
        result["message"] = "Houdini launched. RPyC not yet checked."
        return result

    # Wait for RPyC server to become reachable.
    # Houdini GUI can take 30-90s to start — this is normal.
    start_time = time.time()
    port_open_since = None
    connect_attempts = 0

    while time.time() - start_time < timeout:
        if proc.poll() is not None:
            houdini.unregister_process(port)
            raise RuntimeError(
                f"Houdini process exited with code {proc.returncode}"
            )

        if _is_port_open(port):
            if port_open_since is None:
                port_open_since = time.time()

            # Give Houdini a moment after port opens before first connect
            if time.time() - port_open_since >= 1.0:
                connect_attempts += 1
                try:
                    houdini.connect(port=port)
                    elapsed = int(time.time() - start_time)
                    result["rpyc_connected"] = True
                    result["session_id"] = get_session_id()
                    result["startup_seconds"] = elapsed
                    result["message"] = (
                        f"Houdini {version} ({mode}) ready on port {port} "
                        f"after {elapsed}s. Session: {result['session_id']}"
                    )
                    return result
                except Exception as e:
                    result["rpyc_connect_error"] = str(e)
        else:
            # Port closed again (Houdini might be restarting internals)
            port_open_since = None

        time.sleep(2)

    elapsed = int(time.time() - start_time)
    result["rpyc_connected"] = False
    result["connect_attempts"] = connect_attempts
    result["message"] = (
        f"Houdini launched but RPyC not reachable after {elapsed}s "
        f"({connect_attempts} connect attempts). "
        f"This may mean Houdini is still loading — try ensure_houdini_ready() again."
    )
    return result


@mcp.tool()
def stop_houdini(force: bool = False, port: int | None = None) -> dict:
    """Stop the Houdini process that was launched by start_houdini.

    Args:
        force: If True, force-kill the process. If False, try graceful shutdown first.
        port: Specific port to stop. If None, stops the active connection's Houdini.

    Returns:
        Dict with shutdown status.
    """
    target_port = port or houdini._active_port

    # Get the session ID for the target connection
    target_conn = houdini._connections.get(target_port) if target_port else None
    session_id = target_conn._session_id if target_conn else get_session_id()

    # Try graceful shutdown via RPyC first
    if not force and target_conn and target_conn.is_connected():
        try:
            hou = target_conn.hou
            hou.exit(exit_code=0, suppress_save_prompt=True)
        except Exception:
            pass

    proc = houdini.get_process(target_port)
    if proc is not None:
        if proc.poll() is None:
            if force:
                proc.kill()
            else:
                proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

        exit_code = proc.returncode
        houdini.unregister_process(target_port)
        houdini.disconnect(port=target_port)
        if session_id:
            registry.unregister_session(session_id)
        return {
            "status": "stopped",
            "method": "force" if force else "terminate",
            "exit_code": exit_code,
            "port": target_port,
            "session_id": session_id,
        }

    # No owned process — just disconnect
    houdini.disconnect(port=target_port)
    if session_id:
        registry.unregister_session(session_id)
    return {
        "status": "no_managed_process",
        "port": target_port,
        "message": "No Houdini process was managed by this server on this port.",
    }


@mcp.tool()
def ensure_houdini_ready(
    version: str | None = None,
    mode: str = "gui",
    timeout: int = 120,
) -> dict:
    """Ensure Houdini is running and MCP is connected. Start it if needed.

    This is the recommended single-call entry point for agents.
    Idempotent — safe to call multiple times.

    IMPORTANT: Houdini is a large application that takes 30-90 seconds
    to start up in GUI mode. This is completely normal. The tool handles
    waiting and retrying automatically — just let it run. Do NOT reduce
    the timeout or assume failure while it is still waiting.

    Args:
        version: Houdini version to use if launching (default: latest).
        mode: 'hython' (headless, reliable) or 'gui' (full UI).
        timeout: Max seconds to wait for Houdini startup (default 120).
                 Houdini GUI typically needs 60-90s. Do not lower this.

    Returns:
        Dict with final connection status.
    """
    # Already connected?
    if houdini.is_connected():
        return {
            "status": "ready",
            "port": houdini._explicit_port,
            "session_id": get_session_id(),
            "message": "Houdini already connected via RPyC.",
        }

    # Try connecting (auto-discover or use explicit port)
    try:
        houdini.connect()
        return {
            "status": "ready",
            "port": houdini._explicit_port,
            "session_id": get_session_id(),
            "message": "Connected to existing Houdini RPyC server.",
        }
    except Exception:
        pass

    # Need to launch Houdini
    return start_houdini(version=version, mode=mode, wait_for_rpyc=True, timeout=timeout)
