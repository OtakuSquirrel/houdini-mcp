"""Session registry for Houdini MCP.

Manages session files in ~/houdini_mcp/sessions/ to track active
Houdini instances, their ports, PIDs, and status.

Each MCP server instance registers itself on startup and unregisters
on shutdown. The WebUI and other tools can scan the registry to
discover all active sessions.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from houdini_mcp.config import SESSIONS_DIR, get_port_range

logger = logging.getLogger(__name__)


def generate_session_id() -> str:
    """Generate a short unique session ID."""
    return uuid.uuid4().hex[:12]


def _session_file(session_id: str) -> Path:
    """Path to a session's JSON file."""
    return SESSIONS_DIR / f"{session_id}.json"


def register_session(
    session_id: str,
    port: int,
    pid: int,
    version: str = "",
    mode: str = "gui",
    launched_by: str = "agent",
    houdini_pid: int | None = None,
    client_name: str = "Agent",
) -> dict[str, Any]:
    """Register a new session in the registry.

    Args:
        session_id: Unique session identifier.
        port: RPyC port the Houdini instance listens on.
        pid: OS process ID of the MCP server process.
        version: Houdini version string (e.g. '21.0.551').
        mode: 'gui' or 'hython'.
        launched_by: 'agent' or 'human'.
        houdini_pid: OS process ID of the Houdini instance (if known).

    Returns:
        The session info dict that was written.
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    session_info = {
        "session_id": session_id,
        "port": port,
        "pid": pid,
        "houdini_pid": houdini_pid,
        "version": version,
        "mode": mode,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "launched_by": launched_by,
        "client_name": client_name,
    }

    path = _session_file(session_id)
    path.write_text(
        json.dumps(session_info, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Registered session %s on port %d (pid %d)", session_id, port, pid)
    return session_info


def unregister_session(session_id: str) -> bool:
    """Remove a session from the registry.

    Returns:
        True if the session file was removed, False if it didn't exist.
    """
    path = _session_file(session_id)
    if path.exists():
        path.unlink()
        logger.info("Unregistered session %s", session_id)
        return True
    return False


def get_session(session_id: str) -> dict[str, Any] | None:
    """Read a session's info from the registry.

    Returns:
        Session info dict, or None if not found.
    """
    path = _session_file(session_id)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read session %s: %s", session_id, e)
        return None


def list_sessions() -> list[dict[str, Any]]:
    """List all registered sessions.

    Returns:
        List of session info dicts.
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sessions = []
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            text = f.read_text(encoding="utf-8")
            info = json.loads(text)
            sessions.append(info)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping malformed session file %s: %s", f.name, e)
    return sessions


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    if os.name == "nt":
        # Windows: use tasklist
        import subprocess
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        # Unix: signal 0
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _is_port_in_use(port: int, timeout: float = 0.15) -> bool:
    """Check if a TCP port is in use.

    Uses a short timeout since we only scan localhost — connection refused
    is instant, and a listening port responds in < 1ms.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("localhost", port)) == 0


def cleanup_stale_sessions() -> list[str]:
    """Remove sessions whose MCP server processes are no longer running.

    Checks the "pid" field (MCP server PID). If the MCP server process
    is dead, the session is stale and gets removed.

    Returns:
        List of session IDs that were cleaned up.
    """
    cleaned = []
    for session in list_sessions():
        mcp_pid = session.get("pid")
        if mcp_pid is not None and not _is_pid_alive(mcp_pid):
            session_id = session["session_id"]
            unregister_session(session_id)
            cleaned.append(session_id)
            logger.info("Cleaned stale session %s (MCP pid %d dead)", session_id, mcp_pid)
    return cleaned


def allocate_port() -> int:
    """Find the next available port in the configured range.

    Checks both the session registry and OS port availability.

    Returns:
        An available port number.

    Raises:
        RuntimeError: If no ports are available in the range.
    """
    min_port, max_port = get_port_range()

    # Collect ports used by registered sessions
    used_ports = {s["port"] for s in list_sessions() if "port" in s}

    for port in range(min_port, max_port + 1):
        if port in used_ports:
            continue
        if not _is_port_in_use(port):
            return port

    raise RuntimeError(
        f"No available ports in range {min_port}-{max_port}. "
        f"Run cleanup_stale_sessions() or increase port_range in config."
    )
