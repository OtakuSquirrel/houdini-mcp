"""RPyC connection manager for Houdini.

Connects to Houdini's hrpyc server (RPyC classic mode) and provides
a managed `hou` module proxy with automatic reconnection.

Port resolution (in priority order):
  1. Explicit port passed to constructor (from CLI --port)
  2. HOUDINI_MCP_PORT environment variable
  3. Auto-discovery: scan configured port range for an active RPyC listener

Session registration is lazy — only happens on first successful connect.
This prevents port occupation when the MCP server is idle.
"""

from __future__ import annotations

import atexit
import logging
import os
import socket
import subprocess

import rpyc

logger = logging.getLogger(__name__)

# Default port when nothing else is specified and auto-discovery fails
_DEFAULT_PORT = 18811


def _resolve_default_port() -> int:
    """Determine default RPyC port from env var or fallback."""
    env_port = os.environ.get("HOUDINI_MCP_PORT", "").strip()
    if env_port and env_port != "auto":
        try:
            return int(env_port)
        except ValueError:
            pass
    return _DEFAULT_PORT


def discover_rpyc_port(timeout: float = 0.15) -> int | None:
    """Scan the configured port range for an available Houdini RPyC listener.

    Prefers ports that are listening but DON'T already have an MCP session
    registered (i.e. unlinked Houdini instances). Falls back to any listening
    port if all listening ports already have sessions.

    Returns the port number, or None if no Houdini found.
    """
    from houdini_mcp.config import get_port_range

    min_port, max_port = get_port_range()
    logger.info("Scanning ports %d-%d for Houdini RPyC ...", min_port, max_port)

    # Get ports that already have registered sessions
    try:
        from houdini_mcp.registry import list_sessions, _is_pid_alive
        session_ports = set()
        for s in list_sessions():
            mcp_pid = s.get("pid")
            if s.get("port") and mcp_pid and _is_pid_alive(mcp_pid):
                session_ports.add(s["port"])
    except Exception:
        session_ports = set()

    listening_unlinked = []
    listening_linked = []

    for port in range(min_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            if s.connect_ex(("localhost", port)) == 0:
                if port in session_ports:
                    listening_linked.append(port)
                else:
                    listening_unlinked.append(port)

    # Prefer unlinked ports (Houdini waiting for an MCP connection)
    if listening_unlinked:
        port = listening_unlinked[0]
        logger.info("Found unlinked RPyC listener on port %d", port)
        return port

    # Fall back to any listening port
    if listening_linked:
        port = listening_linked[0]
        logger.info("Found RPyC listener on port %d (already has session)", port)
        return port

    logger.info("No Houdini RPyC listeners found in port range")
    return None


class HoudiniConnection:
    """Manages an RPyC connection to a running Houdini instance.

    Houdini must have its RPyC server running (via hrpyc.start_server).
    We connect using rpyc.classic.connect() to get full access to hou module.

    If port is None, the connection will auto-discover a Houdini RPyC
    listener when first needed (lazy connect).

    Session registration is lazy — happens on first successful connect()
    and is cleaned up on disconnect() or process exit.
    """

    def __init__(self, host: str = "localhost", port: int | None = None):
        self.host = host
        self._explicit_port = port  # None means auto-discover
        self._conn: rpyc.Connection | None = None
        self._session_id: str | None = None
        self._session_registered: bool = False
        self._atexit_registered: bool = False
        self._client_name: str = "Agent"

    @property
    def port(self) -> int:
        """Current target port. Resolves via auto-discovery if not set."""
        if self._explicit_port is not None:
            return self._explicit_port
        # Try env var
        env_port = os.environ.get("HOUDINI_MCP_PORT", "").strip()
        if env_port and env_port != "auto":
            try:
                return int(env_port)
            except ValueError:
                pass
        return _DEFAULT_PORT

    def connect(self, port: int | None = None) -> None:
        """Establish RPyC connection to Houdini.

        Args:
            port: Specific port to connect to. If None, uses the explicit port
                  or auto-discovers by scanning the port range.

        On each new connection, any previous session is unregistered and a
        fresh session is created. One MCP server = one active session.
        """
        # Clean up any existing connection and session
        if self._conn is not None:
            self._conn = None
            logger.info("Dropped previous connection.")
        self._unregister_session()
        # Note: _session_id is NOT cleared here. If pre-set (via --session-id),
        # it's reused. If None, _register_session_lazy() generates a new one.
        # release() clears _session_id for a full reset.

        # Override port if specified
        if port is not None:
            self._explicit_port = port

        # Auto-discover if no explicit port
        if self._explicit_port is None:
            discovered = discover_rpyc_port()
            if discovered is not None:
                self._explicit_port = discovered
            else:
                # Fall back to default — will fail if nothing is listening,
                # but gives a clear error message to the agent
                self._explicit_port = _resolve_default_port()
                logger.warning(
                    "No Houdini RPyC found, falling back to default port %d",
                    self._explicit_port,
                )

        logger.info("Connecting to Houdini at %s:%d ...", self.host, self._explicit_port)
        self._conn = rpyc.classic.connect(self.host, self._explicit_port)
        logger.info("Connected to Houdini successfully on port %d.", self._explicit_port)

        # Register a new session for this connection
        self._register_session_lazy()

    def disconnect(self) -> None:
        """Close the RPyC connection and unregister the session.

        Sends a close message to the remote side. Use release() instead
        if you want to disconnect without affecting Houdini's RPyC server.
        """
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            logger.info("Disconnected from Houdini.")

        self._unregister_session()

    def release(self) -> None:
        """Release the connection without notifying Houdini.

        Abandons the RPyC connection reference and unregisters the session,
        but does NOT send a close message to Houdini. This keeps Houdini's
        RPyC listener alive so another agent can connect later.

        Resets all state so the next connect() starts fresh.
        """
        if self._conn is not None:
            self._conn = None
            logger.info("Released Houdini connection (RPyC listener preserved).")

        self._unregister_session()
        self._session_id = None
        self._explicit_port = None

    def is_connected(self) -> bool:
        """Check if connection is alive by pinging."""
        if self._conn is None:
            return False
        try:
            self._conn.ping()
            return True
        except Exception:
            self._conn = None
            return False

    def _ensure_connected(self) -> None:
        """Reconnect if needed."""
        if not self.is_connected():
            self.connect()

    @property
    def conn(self) -> rpyc.Connection:
        """Get the raw RPyC connection, reconnecting if needed."""
        self._ensure_connected()
        assert self._conn is not None
        return self._conn

    @property
    def hou(self):
        """Get the remote hou module. Auto-reconnects if disconnected."""
        return self.conn.modules.hou

    # ------------------------------------------------------------------
    # Lazy session registration
    # ------------------------------------------------------------------

    def _register_session_lazy(self) -> None:
        """Register this MCP↔Houdini pairing in the session registry.

        Called after each successful connect(). Queries the remote Houdini
        process for its PID and version so the WebUI can display them.
        Stores BOTH the MCP server PID (this process) and Houdini PID (remote)
        so dual-state tracking works correctly.

        Previous sessions are cleaned up by connect() before calling this.
        """
        if self._session_registered:
            return

        try:
            from houdini_mcp.registry import register_session, generate_session_id

            # Generate session ID if not pre-set (e.g. from CLI --session-id)
            if self._session_id is None:
                self._session_id = generate_session_id()

            # MCP server PID = this process
            mcp_pid = os.getpid()

            # Query Houdini for its PID and version via the RPyC connection
            try:
                houdini_pid = self._conn.modules.os.getpid()
            except Exception:
                houdini_pid = None

            try:
                hou = self._conn.modules.hou
                ver = hou.applicationVersionString()
            except Exception:
                ver = ""

            register_session(
                session_id=self._session_id,
                port=self._explicit_port,
                pid=mcp_pid,
                houdini_pid=houdini_pid,
                version=ver,
                launched_by="agent",
                client_name=self._client_name,
            )

            # Also update module-level session ID in server.py
            try:
                import houdini_mcp.server as _srv
                _srv._session_id = self._session_id
            except Exception:
                pass

            # Clean up session when the MCP server process exits (once)
            if not self._atexit_registered:
                atexit.register(self._unregister_session)
                self._atexit_registered = True
            self._session_registered = True

            logger.info(
                "Session %s registered (port %d, MCP pid %d, Houdini pid %s, ver %s)",
                self._session_id, self._explicit_port, mcp_pid, houdini_pid, ver,
            )
        except Exception as e:
            # Non-fatal — MCP still works without session tracking
            logger.warning("Session registration failed (non-fatal): %s", e)

    def _unregister_session(self) -> None:
        """Remove this session from the registry."""
        if not self._session_registered or self._session_id is None:
            return

        try:
            from houdini_mcp.registry import unregister_session
            unregister_session(self._session_id)
            logger.info("Session %s unregistered", self._session_id)
        except Exception as e:
            logger.warning("Session unregister failed: %s", e)
        finally:
            self._session_registered = False


class ConnectionManager:
    """Proxy that manages multiple HoudiniConnection instances.

    Transparent to tool modules — exposes the same interface as HoudiniConnection.
    Delegates .hou, .conn, .port, .is_connected() to the "active" connection.

    Maintains a pool of connections keyed by port, with one designated as
    "active". All existing tool modules (scene, nodes, parameters, etc.)
    continue to work unchanged — they just access houdini.hou / houdini.conn.

    Also tracks process ownership: which Houdini instances were launched
    by this MCP server (owned) vs pre-existing ones (adopted).
    """

    def __init__(self):
        self._connections: dict[int, HoudiniConnection] = {}  # port → conn
        self._active_port: int | None = None
        self._processes: dict[int, subprocess.Popen] = {}  # port → Popen (owned)
        self._explicit_port: int | None = None  # compat with lifecycle.py reads
        self._session_id: str | None = None  # compat with server.py reads
        self._client_name: str = "Agent"  # propagated to HoudiniConnection

    # ------------------------------------------------------------------
    # Active connection access (used by all tool modules)
    # ------------------------------------------------------------------

    @property
    def hou(self):
        """Get the remote hou module from the active connection."""
        return self._active.hou

    @property
    def conn(self) -> rpyc.Connection:
        """Get the raw RPyC connection from the active connection."""
        return self._active.conn

    @property
    def port(self) -> int:
        """Current active port."""
        if self._active_port is not None:
            return self._active_port
        return _resolve_default_port()

    def is_connected(self) -> bool:
        """Check if the active connection is alive."""
        if self._active_port is None:
            return False
        active = self._connections.get(self._active_port)
        return active.is_connected() if active else False

    @property
    def _active(self) -> HoudiniConnection:
        """Get the active connection, auto-connecting if needed."""
        if self._active_port is not None:
            conn = self._connections.get(self._active_port)
            if conn is not None:
                return conn
        # No active connection — auto-discover and connect
        self.connect()
        return self._connections[self._active_port]

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, port: int | None = None) -> None:
        """Connect to a Houdini on the given port (or auto-discover).

        Creates a new HoudiniConnection for this port if needed,
        then sets it as the active connection.
        """
        if port is None:
            port = self._explicit_port
        if port is None:
            discovered = discover_rpyc_port()
            port = discovered if discovered else _resolve_default_port()

        if port not in self._connections:
            hc = HoudiniConnection()
            hc._client_name = self._client_name
            self._connections[port] = hc

        self._connections[port].connect(port=port)
        self._active_port = port
        self._explicit_port = port
        self._session_id = self._connections[port]._session_id

    def disconnect(self, port: int | None = None) -> None:
        """Hard disconnect — sends close to Houdini's RPyC server.

        Used by stop_houdini(). If port is None, disconnects the active connection.
        Auto-switches active to the next available connection.
        """
        port = port or self._active_port
        if port and port in self._connections:
            self._connections[port].disconnect()
            del self._connections[port]
            if self._active_port == port:
                self._active_port = next(iter(self._connections), None)
                self._explicit_port = self._active_port
                self._session_id = (
                    self._connections[self._active_port]._session_id
                    if self._active_port else None
                )

    def release(self, port: int | None = None) -> None:
        """Soft disconnect — preserves Houdini's RPyC listener.

        Used by disconnect_houdini tool. If port is None, releases the active connection.
        Auto-switches active to the next available connection.
        """
        port = port or self._active_port
        if port and port in self._connections:
            self._connections[port].release()
            del self._connections[port]
            if self._active_port == port:
                self._active_port = next(iter(self._connections), None)
                self._explicit_port = self._active_port
                self._session_id = (
                    self._connections[self._active_port]._session_id
                    if self._active_port else None
                )

    def switch_active(self, port: int) -> None:
        """Switch which connection is active.

        If the connection exists but is not connected, reconnects it.
        Raises ValueError if no connection exists on that port.
        """
        if port not in self._connections:
            raise ValueError(
                f"No connection on port {port}. Use connect_to_houdini({port}) first."
            )
        if not self._connections[port].is_connected():
            self._connections[port].connect(port=port)
        self._active_port = port
        self._explicit_port = port
        self._session_id = self._connections[port]._session_id

    def list_connections(self) -> list[dict]:
        """Return info about all managed connections."""
        result = []
        for port, conn in self._connections.items():
            result.append({
                "port": port,
                "connected": conn.is_connected(),
                "active": port == self._active_port,
                "owned": port in self._processes,
                "session_id": conn._session_id,
            })
        return result

    # ------------------------------------------------------------------
    # Process ownership tracking
    # ------------------------------------------------------------------

    def register_process(self, port: int, proc: subprocess.Popen) -> None:
        """Record that this MCP server launched the Houdini on this port."""
        self._processes[port] = proc

    def get_process(self, port: int | None = None) -> subprocess.Popen | None:
        """Get the Popen for a managed Houdini process."""
        port = port or self._active_port
        return self._processes.get(port) if port else None

    def unregister_process(self, port: int) -> subprocess.Popen | None:
        """Remove and return the Popen for a managed Houdini process."""
        return self._processes.pop(port, None)

    def owned_ports(self) -> list[int]:
        """Ports of Houdini processes launched by this MCP."""
        return list(self._processes.keys())
