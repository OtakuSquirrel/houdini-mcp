"""FastMCP server definition for the Houdini MCP Server.

Creates the MCP server instance, initializes the RPyC connection,
and registers all tool modules.

The RPyC port is determined by (in priority order):
  1. Explicit set_port() call (from CLI --port argument)
  2. HOUDINI_MCP_PORT environment variable
  3. Default: 18811
"""

import logging
import os

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware

from houdini_mcp.connection import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Session tracking — set by __main__.py or start_houdini()
_session_id: str | None = None

# Global connection manager — shared by all tool modules
# Proxy that manages multiple HoudiniConnection instances,
# delegating to the "active" one transparently.
houdini = ConnectionManager()


# ── Auto-detect client name from MCP protocol handshake ──
class _ClientNameMiddleware(Middleware):
    """Capture client name from the MCP initialize handshake.

    Every MCP client sends clientInfo.name during initialization.
    We use this to auto-detect the agent/client identity (e.g. "Claude Code",
    "Cursor", etc.) so the WebUI dashboard shows the real name instead of
    a generic "Agent" label.

    """

    async def on_initialize(self, context, call_next):
        result = await call_next(context)
        try:
            name = context.message.params.clientInfo.name
            if name:
                houdini._client_name = name
                logger.info("Client name auto-detected: '%s'", name)
        except Exception:
            pass
        return result


# FastMCP server
mcp = FastMCP(
    "houdini",
    instructions="MCP Server for controlling Houdini via RPyC",
    middleware=[_ClientNameMiddleware()],
)


def set_port(port: int) -> None:
    """Override the RPyC port for the global connection.

    Sets the port on the existing HoudiniConnection instance (does NOT
    replace it) so all tool modules keep a valid reference.
    """
    houdini._explicit_port = port
    logger.info("RPyC target port set to %d", port)


def set_session_id(sid: str) -> None:
    """Set the session ID for this MCP server instance."""
    global _session_id
    _session_id = sid
    houdini._session_id = sid


def get_session_id() -> str | None:
    """Get the current session ID (may be None if not yet connected)."""
    return _session_id or houdini._session_id


# Import tool modules to register their tools on `mcp`.
# Each module imports `mcp` and `houdini` from this module.
import houdini_mcp.tools.scene  # noqa: E402, F401
import houdini_mcp.tools.nodes  # noqa: E402, F401
import houdini_mcp.tools.parameters  # noqa: E402, F401
import houdini_mcp.tools.connections  # noqa: E402, F401
import houdini_mcp.tools.execution  # noqa: E402, F401
import houdini_mcp.tools.geometry  # noqa: E402, F401
import houdini_mcp.tools.viewport  # noqa: E402, F401
import houdini_mcp.tools.render  # noqa: E402, F401
import houdini_mcp.tools.verification  # noqa: E402, F401
import houdini_mcp.tools.lifecycle  # noqa: E402, F401
import houdini_mcp.tools.screen  # noqa: E402, F401
import houdini_mcp.tools.events  # noqa: E402, F401
import houdini_mcp.tools.sessions  # noqa: E402, F401
