"""FastMCP server definition for the Houdini MCP Server.

Creates the MCP server instance, initializes the RPyC connection,
and registers all tool modules.
"""

import logging

from fastmcp import FastMCP

from houdini_mcp.connection import HoudiniConnection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global connection instance — shared by all tool modules
houdini = HoudiniConnection()

# FastMCP server
mcp = FastMCP(
    "houdini",
    instructions="MCP Server for controlling Houdini via RPyC",
)

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
