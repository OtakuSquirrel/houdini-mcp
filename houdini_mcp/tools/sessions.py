"""Session management tools — discover, list, and manage Houdini sessions.

These tools allow agents and users to view all active Houdini MCP sessions
across the system, clean up stale sessions, and get details about the
current session.
"""

from __future__ import annotations

from houdini_mcp.server import mcp, houdini, get_session_id
from houdini_mcp import registry
from houdini_mcp import config


@mcp.tool()
def list_all_sessions() -> dict:
    """List all registered Houdini MCP sessions on this machine.

    Scans ~/houdini_mcp/sessions/ for session files. Each session represents
    a Houdini instance that was started with MCP support.

    Returns:
        Dict with list of sessions and summary info.
    """
    # Clean stale sessions first
    cleaned = registry.cleanup_stale_sessions()

    sessions = registry.list_sessions()

    return {
        "sessions": sessions,
        "total": len(sessions),
        "cleaned_stale": cleaned,
        "current_session_id": get_session_id(),
    }


@mcp.tool()
def disconnect_houdini() -> dict:
    """Disconnect from the current Houdini instance.

    Releases the RPyC connection and unregisters the session.
    The MCP server stays running in idle mode and can reconnect later.
    Houdini itself is NOT affected — its RPyC listener stays active
    and ready for a new connection.

    Returns:
        Dict with disconnection status.
    """
    session_id = get_session_id()
    was_connected = houdini.is_connected()
    port = houdini._active_port

    houdini.release(port=port)

    # Update module-level session ID in server.py
    import houdini_mcp.server as _srv
    _srv._session_id = houdini._session_id

    return {
        "disconnected": was_connected,
        "session_id": session_id,
        "port": port,
        "message": "Disconnected. Houdini RPyC still listening."
            if was_connected else "Was not connected.",
        "remaining_connections": houdini.list_connections(),
    }


@mcp.tool()
def get_current_session() -> dict:
    """Get information about this MCP server's Houdini session.

    Returns:
        Dict with session ID, port, connection status.
    """
    session_id = get_session_id()
    session_info = None
    if session_id:
        session_info = registry.get_session(session_id)

    return {
        "session_id": session_id,
        "port": houdini.port,
        "connected": houdini.is_connected(),
        "registry_info": session_info,
        "connections": houdini.list_connections(),
    }


@mcp.tool()
def cleanup_stale_sessions() -> dict:
    """Remove sessions whose Houdini processes are no longer running.

    Scans all registered sessions and removes those with dead PIDs.

    Returns:
        Dict with list of cleaned session IDs.
    """
    cleaned = registry.cleanup_stale_sessions()
    remaining = registry.list_sessions()

    return {
        "cleaned": cleaned,
        "cleaned_count": len(cleaned),
        "remaining_sessions": len(remaining),
    }


@mcp.tool()
def scan_ports() -> dict:
    """Scan the configured port range and report Houdini RPyC + MCP server status.

    For each port in the range, checks TWO independent states:
    - **houdini_rpyc**: Is a Houdini RPyC server listening on this port?
    - **mcp_server**: Is there a registered MCP server session whose process is alive?

    Combined states for each active port:
    - "linked":   Houdini RPyC active + MCP server alive → fully operational
    - "mcp_idle": MCP server alive but Houdini RPyC down → run RPyC in Houdini to reconnect
    - "orphaned": Houdini RPyC active but MCP server dead → start MCP server to connect
    - "stale":    Both dead → cleanup candidate
    - "listening": Houdini RPyC active, no session registered → start MCP server to connect

    Also returns `next_free_port` — the first port where neither Houdini nor
    MCP is active, ready for a new session.

    Returns:
        Dict with port range, active ports with dual status, free count,
        and next_free_port with ready-to-use commands.
    """
    from concurrent.futures import ThreadPoolExecutor

    min_port, max_port = config.get_port_range()
    sessions = registry.list_sessions()
    session_ports = {s["port"]: s for s in sessions if "port" in s}

    ports = list(range(min_port, max_port + 1))

    with ThreadPoolExecutor(max_workers=30) as executor:
        listening_flags = list(executor.map(registry._is_port_in_use, ports))

    # Check MCP server PIDs (session "pid" = MCP server process)
    session_pids_alive = {}
    for port_num, s in session_ports.items():
        mcp_pid = s.get("pid")
        session_pids_alive[port_num] = registry._is_pid_alive(mcp_pid) if mcp_pid else False

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
                "houdini_rpyc": is_listening,
                "mcp_server": mcp_alive,
                "session_id": s.get("session_id"),
                "mcp_pid": s.get("pid"),
                "houdini_pid": s.get("houdini_pid"),
                "launched_by": s.get("launched_by", ""),
            })
        elif is_listening:
            active.append({
                "port": port,
                "status": "listening",
                "houdini_rpyc": True,
                "mcp_server": False,
            })
        else:
            free_count += 1
            if next_free_port is None:
                next_free_port = port

    result = {
        "range": [min_port, max_port],
        "active": active,
        "free_count": free_count,
        "next_free_port": next_free_port,
        "total_ports": max_port - min_port + 1,
    }

    if next_free_port:
        result["next_free_commands"] = {
            "houdini_python": f"import hrpyc; hrpyc.start_server(port={next_free_port})",
            "terminal_mcp": f".venv\\Scripts\\python.exe -m houdini_mcp --port {next_free_port}",
        }

    return result


@mcp.tool()
def get_mcp_config() -> dict:
    """Get the current MCP configuration.

    Returns the contents of ~/houdini_mcp/config.json including:
    - human_launch settings (whether RPyC auto-starts for manual Houdini)
    - agent_launch settings
    - port_range for dynamic allocation

    Returns:
        The full config dict.
    """
    return config.load_config()


@mcp.tool()
def update_mcp_config(
    human_auto_start: bool | None = None,
    agent_auto_start: bool | None = None,
    port_range_min: int | None = None,
    port_range_max: int | None = None,
) -> dict:
    """Update MCP configuration settings.

    Changes are written to ~/houdini_mcp/config.json and take effect
    on next Houdini launch or MCP server start.

    Args:
        human_auto_start: Whether human-launched Houdini should auto-start RPyC.
        agent_auto_start: Whether agent-launched Houdini should auto-start RPyC.
        port_range_min: Minimum port number for dynamic allocation.
        port_range_max: Maximum port number for dynamic allocation.

    Returns:
        The updated config dict.
    """
    updates = {}
    if human_auto_start is not None:
        updates["human_launch"] = {"auto_start_rpyc": human_auto_start}
    if agent_auto_start is not None:
        updates["agent_launch"] = {"auto_start_rpyc": agent_auto_start}
    if port_range_min is not None or port_range_max is not None:
        current = config.load_config()
        current_range = current.get("port_range", [18811, 18899])
        updates["port_range"] = [
            port_range_min if port_range_min is not None else current_range[0],
            port_range_max if port_range_max is not None else current_range[1],
        ]

    if not updates:
        return config.load_config()

    return config.update_config(updates)


@mcp.tool()
def connect_to_houdini(port: int) -> dict:
    """Connect to a Houdini instance on a specific port.

    Establishes an RPyC connection and makes it the active connection
    for all subsequent operations. Can connect to multiple Houdini
    instances simultaneously — use switch_active_houdini to change
    which one receives commands.

    Args:
        port: The RPyC port of the Houdini instance to connect to.

    Returns:
        Dict with connection status and active connection info.
    """
    houdini.connect(port=port)

    # Update module-level session ID in server.py
    import houdini_mcp.server as _srv
    _srv._session_id = houdini._session_id

    return {
        "status": "connected",
        "port": port,
        "active": True,
        "session_id": houdini._session_id,
        "total_connections": len(houdini._connections),
        "connections": houdini.list_connections(),
    }


@mcp.tool()
def switch_active_houdini(port: int) -> dict:
    """Switch which Houdini instance receives commands.

    The target must already be connected (use connect_to_houdini first).
    All subsequent operations (create_node, set_parameter, etc.) will
    go to the switched-to Houdini instance.

    Args:
        port: The RPyC port of the Houdini instance to switch to.

    Returns:
        Dict with switch status and connection info.
    """
    houdini.switch_active(port)

    # Update module-level session ID in server.py
    import houdini_mcp.server as _srv
    _srv._session_id = houdini._session_id

    return {
        "status": "switched",
        "active_port": port,
        "session_id": houdini._session_id,
        "connections": houdini.list_connections(),
    }


@mcp.tool()
def list_houdini_connections() -> dict:
    """List all Houdini connections managed by this MCP server.

    Shows which connections are active, connected, and owned
    (launched by this MCP server) vs adopted (pre-existing).

    Returns:
        Dict with connection list and active port.
    """
    return {
        "connections": houdini.list_connections(),
        "active_port": houdini._active_port,
        "owned_ports": houdini.owned_ports(),
        "total": len(houdini._connections),
    }
