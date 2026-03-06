"""Configuration management API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from houdini_mcp import config

router = APIRouter()


class ConfigUpdate(BaseModel):
    """Request body for config updates."""
    human_launch: dict[str, Any] | None = None
    agent_launch: dict[str, Any] | None = None
    port_range: list[int] | None = None
    houdini_search_paths: list[str] | None = None


@router.get("")
async def get_config():
    """Get the current MCP configuration."""
    return config.load_config()


@router.put("")
async def update_config(updates: ConfigUpdate):
    """Update MCP configuration.

    Only provided fields are updated; others are left unchanged.
    """
    update_dict = {}
    if updates.human_launch is not None:
        update_dict["human_launch"] = updates.human_launch
    if updates.agent_launch is not None:
        update_dict["agent_launch"] = updates.agent_launch
    if updates.port_range is not None:
        update_dict["port_range"] = updates.port_range
    if updates.houdini_search_paths is not None:
        update_dict["houdini_search_paths"] = updates.houdini_search_paths

    if not update_dict:
        return config.load_config()

    return config.update_config(update_dict)


@router.post("/reset")
async def reset_config():
    """Reset configuration to defaults."""
    from houdini_mcp.config import _DEFAULT_CONFIG
    config.save_config(dict(_DEFAULT_CONFIG))
    return _DEFAULT_CONFIG
