"""Session management API routes."""

from __future__ import annotations

import os
import re
import subprocess

from fastapi import APIRouter, HTTPException

from houdini_mcp import registry

router = APIRouter()


@router.get("")
async def list_sessions():
    """List all registered Houdini MCP sessions."""
    sessions = registry.list_sessions()
    return {
        "sessions": sessions,
        "total": len(sessions),
    }


@router.post("/cleanup")
async def cleanup_stale():
    """Remove sessions whose processes are no longer running."""
    cleaned = registry.cleanup_stale_sessions()
    remaining = registry.list_sessions()
    return {
        "cleaned": cleaned,
        "cleaned_count": len(cleaned),
        "remaining": len(remaining),
    }


@router.get("/dashboard")
async def dashboard():
    """Get dashboard data with decoupled Houdini and MCP Server lists.

    Returns two independent lists:
    - houdini_instances: all listening Houdini RPyC servers (from port scan)
    - mcp_servers: all active MCP server processes (grouped by MCP PID)
    """
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _build_dashboard)


@router.get("/ports/status")
async def port_status():
    """Get port allocation status with dual-state tracking.

    Checks BOTH the MCP server process (PID alive?) and the Houdini RPyC
    port (TCP listening?) to classify each port into one of these states:

    For ports WITH a registered session:
    - "linked":      MCP server alive + Houdini RPyC listening (fully connected)
    - "mcp_idle":    MCP server alive + Houdini RPyC NOT listening (awaiting reconnect)
    - "orphaned":    MCP server dead  + Houdini RPyC listening (needs new MCP)
    - "stale":       MCP server dead  + Houdini RPyC NOT listening (cleanup candidate)

    For ports WITHOUT a session:
    - "listening":   port is listening (Houdini RPyC active, no MCP connected)
    - "free":        nothing on this port

    Only non-free ports are returned in the `active` list for quick display.
    """
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _scan_ports)


def _get_listening_pids() -> dict[int, int]:
    """Get a mapping of port → PID for all TCP LISTENING ports.

    Uses netstat on Windows, ss on Linux/Mac.
    Returns {port: pid} dict.
    """
    port_pid = {}
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "LISTENING" not in line:
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        addr = parts[1]
                        port = int(addr.rsplit(":", 1)[1])
                        pid = int(parts[4])
                        port_pid[port] = pid
                    except (ValueError, IndexError):
                        pass
        else:
            result = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                # Parse ss output: LISTEN 0 128 127.0.0.1:18811 ... pid=12345
                m_port = re.search(r":(\d+)\s", line)
                m_pid = re.search(r"pid=(\d+)", line)
                if m_port and m_pid:
                    port_pid[int(m_port.group(1))] = int(m_pid.group(1))
    except Exception:
        pass
    return port_pid


def _scan_ports():
    """Synchronous port scanner — runs in thread pool.

    Uses concurrent threads to check all ports in parallel for fast results.
    """
    from concurrent.futures import ThreadPoolExecutor

    from houdini_mcp.config import get_port_range

    min_port, max_port = get_port_range()
    sessions = registry.list_sessions()
    session_ports = {s["port"]: s for s in sessions if "port" in s}

    ports = list(range(min_port, max_port + 1))

    # Scan all ports concurrently — ~89 ports finishes in < 1s
    with ThreadPoolExecutor(max_workers=30) as executor:
        listening_flags = list(executor.map(registry._is_port_in_use, ports))

    # Get PID for each listening port (single OS call, fast)
    listening_pids = _get_listening_pids()

    # Check MCP server PIDs (session "pid" field = MCP server process)
    session_pids_alive = {}
    for port_num, s in session_ports.items():
        mcp_pid = s.get("pid")
        if mcp_pid is not None:
            session_pids_alive[port_num] = registry._is_pid_alive(mcp_pid)
        else:
            session_pids_alive[port_num] = False

    active = []
    free_count = 0
    next_free_port = None

    for port, is_listening in zip(ports, listening_flags):
        has_session = port in session_ports

        if has_session:
            s = session_ports[port]
            mcp_alive = session_pids_alive.get(port, False)

            if mcp_alive and is_listening:
                status = "linked"
            elif mcp_alive and not is_listening:
                status = "mcp_idle"
            elif not mcp_alive and is_listening:
                status = "orphaned"
            else:
                status = "stale"

            active.append({
                "port": port,
                "status": status,
                "session_id": s.get("session_id"),
                "mcp_pid": s.get("pid"),
                "houdini_pid": s.get("houdini_pid") or listening_pids.get(port),
                "mcp_alive": mcp_alive,
                "launched_by": s.get("launched_by", ""),
            })
        elif is_listening:
            active.append({
                "port": port,
                "status": "listening",
                "houdini_pid": listening_pids.get(port),
            })
        else:
            free_count += 1
            if next_free_port is None:
                next_free_port = port

    return {
        "range": [min_port, max_port],
        "active": active,
        "free_count": free_count,
        "next_free_port": next_free_port,
        "total_ports": max_port - min_port + 1,
    }


def _build_dashboard():
    """Build dashboard data with decoupled Houdini and MCP Server lists.

    Combines port scanning (for Houdini RPyC listeners) with session
    registry (for MCP server grouping) into two independent lists.
    """
    from concurrent.futures import ThreadPoolExecutor

    from houdini_mcp.config import get_port_range

    min_port, max_port = get_port_range()
    sessions = registry.list_sessions()
    ports = list(range(min_port, max_port + 1))

    # Scan all ports concurrently
    with ThreadPoolExecutor(max_workers=30) as executor:
        listening_flags = list(executor.map(registry._is_port_in_use, ports))

    listening_pids = _get_listening_pids()
    listening_ports = {p for p, flag in zip(ports, listening_flags) if flag}

    # Build session lookup: port → list of sessions on that port
    port_sessions: dict[int, list] = {}
    for s in sessions:
        p = s.get("port")
        if p is not None:
            port_sessions.setdefault(p, []).append(s)

    # ── Houdini Instances ──
    # Every listening port in range = a Houdini RPyC listener
    houdini_instances = []
    for port in sorted(listening_ports & set(ports)):
        pid = listening_pids.get(port)
        # Try to get version from any session registered on this port
        version = ""
        connected_mcp_pids = []
        for s in port_sessions.get(port, []):
            mcp_pid = s.get("pid")
            if mcp_pid and registry._is_pid_alive(mcp_pid):
                connected_mcp_pids.append(mcp_pid)
            if not version and s.get("version"):
                version = s["version"]

        houdini_instances.append({
            "port": port,
            "pid": pid,
            "version": version,
            "connected_mcp_pids": connected_mcp_pids,
        })

    # ── MCP Servers ──
    # Group sessions by MCP PID (one MCP server = one PID, may have multiple sessions)
    mcp_groups: dict[int, dict] = {}
    for s in sessions:
        mcp_pid = s.get("pid")
        if mcp_pid is None:
            continue
        if mcp_pid not in mcp_groups:
            mcp_groups[mcp_pid] = {
                "mcp_pid": mcp_pid,
                "client_name": s.get("client_name", "Agent"),
                "alive": registry._is_pid_alive(mcp_pid),
                "sessions": [],
            }
        mcp_groups[mcp_pid]["sessions"].append({
            "session_id": s.get("session_id"),
            "port": s.get("port"),
            "houdini_pid": s.get("houdini_pid"),
            "version": s.get("version", ""),
            "created_at": s.get("created_at", ""),
        })

    # Only include alive MCP servers (dead ones are stale), sorted by PID ascending
    mcp_servers = sorted(
        [g for g in mcp_groups.values() if g["alive"]],
        key=lambda g: g["mcp_pid"],
    )
    # Sort each server's sessions by port ascending
    for m in mcp_servers:
        m["sessions"].sort(key=lambda s: s.get("port") or 0)

    # Free port info
    free_count = len(set(ports) - listening_ports - {s.get("port") for s in sessions})
    next_free_port = None
    for p in ports:
        if p not in listening_ports and p not in {s.get("port") for s in sessions}:
            next_free_port = p
            break

    return {
        "houdini_instances": houdini_instances,
        "mcp_servers": mcp_servers,
        "free_count": free_count,
        "next_free_port": next_free_port,
    }


# Parameterized routes MUST come after static routes
@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get details for a specific session."""
    session = registry.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Check if process is still alive
    pid = session.get("pid")
    if pid is not None:
        session["process_alive"] = registry._is_pid_alive(pid)

    # Check if port is reachable
    port = session.get("port")
    if port is not None:
        session["port_reachable"] = registry._is_port_in_use(port)

    return session


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Manually remove a session from the registry."""
    removed = registry.unregister_session(session_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"status": "removed", "session_id": session_id}
