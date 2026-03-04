"""RPyC connection manager for Houdini.

Connects to Houdini's hrpyc server (RPyC classic mode) and provides
a managed `hou` module proxy with automatic reconnection.
"""

import logging

import rpyc

logger = logging.getLogger(__name__)


class HoudiniConnection:
    """Manages an RPyC connection to a running Houdini instance.

    Houdini must have its RPyC server running (via hrpyc.start_server).
    We connect using rpyc.classic.connect() to get full access to hou module.
    """

    def __init__(self, host: str = "localhost", port: int = 18811):
        self.host = host
        self.port = port
        self._conn: rpyc.Connection | None = None

    def connect(self) -> None:
        """Establish RPyC connection to Houdini."""
        if self._conn is not None:
            self.disconnect()
        logger.info("Connecting to Houdini at %s:%d ...", self.host, self.port)
        self._conn = rpyc.classic.connect(self.host, self.port)
        logger.info("Connected to Houdini successfully.")

    def disconnect(self) -> None:
        """Close the RPyC connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            logger.info("Disconnected from Houdini.")

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
