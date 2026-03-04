"""Houdini lifecycle tools — start, stop, status, setup.

Allows the Agent to launch and manage the Houdini process autonomously.
No human intervention needed.

Supports two modes:
- hython (default): Headless Python mode. Always reliable, no GUI dialogs.
- gui: Full Houdini GUI. Requires startup scripts installed (use install_startup_scripts).

Multi-version support: Houdini 20.5+ (auto-detected from install directory).
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

from houdini_mcp.server import mcp, houdini

# Houdini installation discovery (Windows)
_SFX_ROOT = Path("C:/Program Files/Side Effects Software")
_PROCESS: subprocess.Popen | None = None

# Startup script source (single source of truth)
_PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "houdini_plugin"
_STARTUP_SCRIPT = _PLUGIN_DIR / "houdini_mcp_startup.py"


def _find_houdini_installations() -> list[dict]:
    """Discover installed Houdini versions."""
    results = []
    if not _SFX_ROOT.exists():
        return results
    for d in sorted(_SFX_ROOT.iterdir(), reverse=True):
        if d.name.startswith("Houdini ") and d.is_dir():
            version = d.name.replace("Houdini ", "")
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


@mcp.tool()
def install_startup_scripts(version: str | None = None) -> dict:
    """Install RPyC startup scripts into a Houdini version's prefs directory.

    Required for GUI mode — the scripts auto-start the RPyC server when Houdini
    launches, allowing MCP to connect. Safe to run multiple times (idempotent).

    Installs the same script as pythonrc.py, 123.py, and 456.py to cover all
    startup scenarios. Each script checks if the port is already in use before
    starting, so there's no risk of double-starting.

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
        raise RuntimeError(f"No Houdini installations found in {_SFX_ROOT}")

    # Filter to requested version if specified
    if version is not None:
        targets = [i for i in installations if i["version"].startswith(version)]
        if not targets:
            available = [i["version"] for i in installations]
            raise ValueError(
                f"Houdini version '{version}' not found. Available: {available}"
            )
    else:
        targets = installations

    script_names = ["pythonrc.py", "123.py", "456.py"]
    results = {}

    for inst in targets:
        ver = inst["version"]
        prefs_dir = _get_houdini_prefs_dir(ver)
        scripts_dir = prefs_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        installed = []
        for name in script_names:
            dest = scripts_dir / name
            shutil.copy2(str(_STARTUP_SCRIPT), str(dest))
            installed.append(str(dest))

        results[ver] = {
            "prefs_dir": str(prefs_dir),
            "scripts_dir": str(scripts_dir),
            "installed": installed,
        }

    return {
        "status": "installed",
        "versions": results,
        "source": str(_STARTUP_SCRIPT),
    }


@mcp.tool()
def get_houdini_status() -> dict:
    """Check if Houdini is running and the RPyC server is reachable.

    Returns:
        Dict with process status, RPyC connectivity, and installed versions.
    """
    global _PROCESS

    rpyc_reachable = _is_port_open(houdini.port)

    process_alive = False
    process_pid = None
    if _PROCESS is not None:
        poll = _PROCESS.poll()
        if poll is None:
            process_alive = True
            process_pid = _PROCESS.pid
        else:
            _PROCESS = None

    connected = houdini.is_connected()

    installations = _find_houdini_installations()

    return {
        "rpyc_reachable": rpyc_reachable,
        "rpyc_port": houdini.port,
        "managed_process_alive": process_alive,
        "managed_process_pid": process_pid,
        "mcp_connected": connected,
        "installed_versions": installations,
    }


@mcp.tool()
def start_houdini(
    version: str | None = None,
    mode: str = "gui",
    wait_for_rpyc: bool = True,
    timeout: int = 60,
    open_file: str | None = None,
) -> dict:
    """Launch Houdini and wait for it to be ready for MCP communication.

    Args:
        version: Houdini version to launch (e.g. '21.0.551'). If None, uses latest.
        mode: 'hython' (headless, reliable) or 'gui' (full UI, needs 456.py).
        wait_for_rpyc: Whether to wait until the RPyC server is reachable (default True).
        timeout: Max seconds to wait for RPyC server (default 60).
        open_file: Optional .hip file path to open on launch (gui mode only).

    Returns:
        Dict with process PID and connection status.
    """
    global _PROCESS

    # Check if already running
    if _is_port_open(houdini.port):
        try:
            houdini.connect()
            return {
                "status": "already_running",
                "rpyc_connected": True,
                "message": "Houdini RPyC server already reachable, connected.",
            }
        except Exception:
            pass

    # Find the right executable
    installations = _find_houdini_installations()
    if not installations:
        raise RuntimeError(
            f"No Houdini installation found in {_SFX_ROOT}. "
            "Install Houdini or provide a custom path."
        )

    inst = None
    if version is not None:
        # Support both exact match ("21.0.551") and prefix match ("20.5", "21.0")
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

    if mode == "hython":
        hython_path = inst.get("hython")
        if not hython_path:
            raise RuntimeError(f"hython.exe not found for Houdini {version}")

        # Launch hython with RPyC server inline
        script = (
            "import hrpyc, time, sys; "
            f"hrpyc.start_server(port={houdini.port}); "
            "print('[HoudiniMCP] RPyC server started', flush=True); "
            "[time.sleep(1) for _ in iter(int,1)]"
        )
        _PROCESS = subprocess.Popen(
            [hython_path, "-c", script],
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
        _PROCESS = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    result = {
        "status": "launched",
        "version": version,
        "mode": mode,
        "pid": _PROCESS.pid,
    }

    if not wait_for_rpyc:
        result["rpyc_connected"] = False
        result["message"] = "Houdini launched. RPyC not yet checked."
        return result

    # Wait for RPyC server to become reachable
    start_time = time.time()
    while time.time() - start_time < timeout:
        if _PROCESS.poll() is not None:
            raise RuntimeError(
                f"Houdini process exited with code {_PROCESS.returncode}"
            )
        if _is_port_open(houdini.port):
            time.sleep(1)
            try:
                houdini.connect()
                result["rpyc_connected"] = True
                result["message"] = f"Houdini {version} ({mode}) ready. RPyC connected."
                return result
            except Exception as e:
                result["rpyc_connect_error"] = str(e)
        time.sleep(2)

    result["rpyc_connected"] = False
    result["message"] = f"Houdini launched but RPyC not reachable after {timeout}s."
    return result


@mcp.tool()
def stop_houdini(force: bool = False) -> dict:
    """Stop the Houdini process that was launched by start_houdini.

    Args:
        force: If True, force-kill the process. If False, try graceful shutdown first.

    Returns:
        Dict with shutdown status.
    """
    global _PROCESS

    # Try graceful shutdown via RPyC first
    if not force and houdini.is_connected():
        try:
            hou = houdini.hou
            hou.exit(exit_code=0, suppress_save_prompt=True)
            houdini.disconnect()
            _PROCESS = None
            return {"status": "stopped", "method": "graceful"}
        except Exception:
            pass

    if _PROCESS is not None:
        if _PROCESS.poll() is None:
            if force:
                _PROCESS.kill()
            else:
                _PROCESS.terminate()
            try:
                _PROCESS.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _PROCESS.kill()
                _PROCESS.wait(timeout=5)

        exit_code = _PROCESS.returncode
        _PROCESS = None
        houdini.disconnect()
        return {"status": "stopped", "method": "force" if force else "terminate", "exit_code": exit_code}

    houdini.disconnect()
    return {"status": "no_managed_process", "message": "No Houdini process was managed by this server."}


@mcp.tool()
def ensure_houdini_ready(
    version: str | None = None,
    mode: str = "gui",
    timeout: int = 30,
) -> dict:
    """Ensure Houdini is running and MCP is connected. Start it if needed.

    This is the recommended single-call entry point for agents.
    Idempotent — safe to call multiple times.

    Args:
        version: Houdini version to use if launching (default: latest).
        mode: 'hython' (headless, reliable) or 'gui' (full UI).
        timeout: Max seconds to wait for Houdini startup (default 30).

    Returns:
        Dict with final connection status.
    """
    # Already connected?
    if houdini.is_connected():
        return {
            "status": "ready",
            "message": "Houdini already connected via RPyC.",
        }

    # Port open but not connected? Try connecting.
    if _is_port_open(houdini.port):
        try:
            houdini.connect()
            return {
                "status": "ready",
                "message": "Connected to existing Houdini RPyC server.",
            }
        except Exception:
            pass

    # Need to launch Houdini
    return start_houdini(version=version, mode=mode, wait_for_rpyc=True, timeout=timeout)
