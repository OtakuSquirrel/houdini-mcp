"""FastAPI application for the Houdini MCP WebUI.

Provides REST APIs for:
- Configuration management (read/write ~/houdini_mcp/config.json)
- Session discovery and monitoring
- Houdini installation and process discovery
- Startup script management
- Port allocation status
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from houdini_mcp.webui.routes import config_routes, session_routes, houdini_routes, agent_routes, tool_routes

app = FastAPI(
    title="Houdini MCP Manager",
    description="Web dashboard for managing Houdini MCP sessions and configuration",
    version="0.1.0",
)

# Register route modules
app.include_router(config_routes.router, prefix="/api/config", tags=["config"])
app.include_router(session_routes.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(houdini_routes.router, prefix="/api/houdini", tags=["houdini"])
app.include_router(agent_routes.router, prefix="/api/agents", tags=["agents"])
app.include_router(tool_routes.router, prefix="/api/tools", tags=["tools"])

# Serve static frontend files
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
async def index():
    """Serve the main dashboard page."""
    index_file = _STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Houdini MCP Manager API", "docs": "/docs"}


@app.get("/config")
async def config():
    """Serve the Houdini configuration page."""
    config_file = _STATIC_DIR / "config.html"
    if config_file.exists():
        return FileResponse(str(config_file))
    return {"message": "Config page not found"}


@app.get("/agent-config")
async def agent_config():
    """Serve the agent configuration page."""
    agent_file = _STATIC_DIR / "agent_config.html"
    if agent_file.exists():
        return FileResponse(str(agent_file))
    return {"message": "Agent config page not found"}


@app.get("/tools")
async def tools_page():
    """Serve the MCP Tools management page."""
    tools_file = _STATIC_DIR / "tools.html"
    if tools_file.exists():
        return FileResponse(str(tools_file))
    return {"message": "Tools page not found"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
