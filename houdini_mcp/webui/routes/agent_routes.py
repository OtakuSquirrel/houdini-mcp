"""Agent configuration API routes.

Manages MCP server registration for AI agent clients.
Currently supports Claude Code.

Two independent config scopes:
- Global:   ~/.claude.json        → all projects, uses absolute path
- Project:  <project>/.mcp.json   → single project, uses relative path if possible
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# Claude Code user-level config file
_CLAUDE_CONFIG = Path.home() / ".claude.json"

# HoudiniMCP project root (where the venv lives)
_HOUDINI_MCP_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# The MCP server entry key
_MCP_KEY = "houdini"


def _get_mcp_command_absolute() -> str:
    """Absolute path to the venv Python (for global config)."""
    return sys.executable


def _get_mcp_command_for_project(project_path: Path) -> str:
    """Command path for a project's .mcp.json.

    If the project contains the HoudiniMCP venv, use a relative path.
    Otherwise, use the absolute path.
    """
    venv_python = Path(sys.executable).resolve()
    project_resolved = project_path.resolve()

    try:
        rel = venv_python.relative_to(project_resolved)
        # Relative path within the project — use it
        return str(rel)
    except ValueError:
        # Not inside the project — must use absolute
        return str(venv_python)


def _get_mcp_args() -> list[str]:
    """Args list for launching the MCP server."""
    return ["-m", "houdini_mcp"]


def _build_entry(command: str) -> dict:
    """Build the mcpServers entry dict."""
    return {
        "command": command,
        "args": _get_mcp_args(),
    }


def _read_json_file(path: Path) -> dict:
    """Read a JSON file, returning empty dict if absent or invalid."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        return json.loads(text)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json_file(path: Path, config: dict) -> None:
    """Write a JSON file with pretty formatting."""
    path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _check_mcp_entry(config: dict) -> dict | None:
    """Extract the houdini MCP entry from a config dict."""
    return config.get("mcpServers", {}).get(_MCP_KEY)


def _install_entry(config_path: Path, entry: dict) -> dict:
    """Install houdini entry into a config file. Returns the full entry."""
    config = _read_json_file(config_path)
    if "mcpServers" not in config:
        config["mcpServers"] = {}
    config["mcpServers"][_MCP_KEY] = entry
    _write_json_file(config_path, config)
    return entry


def _uninstall_entry(config_path: Path) -> bool:
    """Remove houdini entry from a config file. Returns True if removed."""
    config = _read_json_file(config_path)
    mcp_servers = config.get("mcpServers", {})
    if _MCP_KEY not in mcp_servers:
        return False
    del mcp_servers[_MCP_KEY]
    if not mcp_servers:
        config.pop("mcpServers", None)
    _write_json_file(config_path, config)
    return True


# ── Global (user-level) ──

@router.get("/claude/global/status")
async def claude_global_status():
    """Check global installation status (~/.claude.json)."""
    config = _read_json_file(_CLAUDE_CONFIG)
    entry = _check_mcp_entry(config)
    expected = _build_entry(_get_mcp_command_absolute())

    result = {
        "installed": entry is not None,
        "config_path": str(_CLAUDE_CONFIG),
        "config_exists": _CLAUDE_CONFIG.exists(),
        "expected_entry": expected,
    }
    if entry:
        result["current_entry"] = entry
        result["up_to_date"] = entry == expected
    else:
        result["up_to_date"] = False

    return result


@router.post("/claude/global/install")
async def claude_global_install():
    """Install to ~/.claude.json (global, absolute path)."""
    entry = _build_entry(_get_mcp_command_absolute())
    try:
        _install_entry(_CLAUDE_CONFIG, entry)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "installed", "config_path": str(_CLAUDE_CONFIG), "entry": entry}


@router.post("/claude/global/uninstall")
async def claude_global_uninstall():
    """Remove from ~/.claude.json."""
    try:
        removed = _uninstall_entry(_CLAUDE_CONFIG)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "status": "uninstalled" if removed else "not_installed",
        "config_path": str(_CLAUDE_CONFIG),
    }


# ── Project-level ──

class ProjectPath(BaseModel):
    path: str


@router.post("/claude/project/status")
async def claude_project_status(body: ProjectPath):
    """Check project-level installation status (<path>/.mcp.json)."""
    project = Path(body.path).resolve()
    if not project.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {body.path}")

    mcp_json = project / ".mcp.json"
    config = _read_json_file(mcp_json)
    entry = _check_mcp_entry(config)

    command = _get_mcp_command_for_project(project)
    expected = _build_entry(command)

    result = {
        "installed": entry is not None,
        "config_path": str(mcp_json),
        "config_exists": mcp_json.exists(),
        "expected_entry": expected,
    }
    if entry:
        result["current_entry"] = entry
        result["up_to_date"] = entry == expected
    else:
        result["up_to_date"] = False

    return result


@router.post("/claude/project/install")
async def claude_project_install(body: ProjectPath):
    """Install to <path>/.mcp.json (project-level, relative path if possible)."""
    project = Path(body.path).resolve()
    if not project.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {body.path}")

    mcp_json = project / ".mcp.json"
    command = _get_mcp_command_for_project(project)
    entry = _build_entry(command)

    try:
        _install_entry(mcp_json, entry)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "installed", "config_path": str(mcp_json), "entry": entry}


@router.post("/claude/project/uninstall")
async def claude_project_uninstall(body: ProjectPath):
    """Remove from <path>/.mcp.json."""
    project = Path(body.path).resolve()
    mcp_json = project / ".mcp.json"

    try:
        removed = _uninstall_entry(mcp_json)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "uninstalled" if removed else "not_installed",
        "config_path": str(mcp_json),
    }
