"""Tool management API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from houdini_mcp import config
from houdini_mcp.tool_registry import (
    CATEGORY_DEFS,
    ALL_TOOL_NAMES,
    DEFAULT_DISABLED_TOOLS,
    get_disabled_tools,
)

router = APIRouter()


class ToolToggle(BaseModel):
    tool_name: str
    enabled: bool


class BulkToggle(BaseModel):
    disabled_tools: list[str]


@router.get("")
async def list_tools():
    """List all tools organized by category with enabled/disabled state."""
    disabled = set(get_disabled_tools())

    categories = []
    for cat_name, cat_info in CATEGORY_DEFS.items():
        tools = []
        for name, desc in cat_info["tools"].items():
            tools.append({
                "name": name,
                "desc": desc,
                "enabled": name not in disabled,
            })
        categories.append({
            "category": cat_name,
            "desc": cat_info["desc"],
            "tools": tools,
            "enabled_count": sum(1 for t in tools if t["enabled"]),
            "total_count": len(tools),
        })

    return {
        "categories": categories,
        "total_tools": len(ALL_TOOL_NAMES),
        "disabled_count": len(disabled & ALL_TOOL_NAMES),
    }


@router.put("/toggle")
async def toggle_tool(body: ToolToggle):
    """Enable or disable a single tool."""
    if body.tool_name not in ALL_TOOL_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {body.tool_name}")

    disabled = set(get_disabled_tools())

    if body.enabled:
        disabled.discard(body.tool_name)
    else:
        disabled.add(body.tool_name)

    config.update_config({"disabled_tools": sorted(disabled)})

    return {
        "tool_name": body.tool_name,
        "enabled": body.enabled,
        "disabled_count": len(disabled & ALL_TOOL_NAMES),
    }


@router.put("/bulk")
async def bulk_update(body: BulkToggle):
    """Set the entire disabled_tools list at once."""
    unknown = set(body.disabled_tools) - ALL_TOOL_NAMES
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown tools: {sorted(unknown)}")

    config.update_config({"disabled_tools": sorted(body.disabled_tools)})

    return {
        "disabled_tools": sorted(body.disabled_tools),
        "disabled_count": len(body.disabled_tools),
    }


@router.post("/reset")
async def reset_tools():
    """Reset disabled tools to defaults."""
    config.update_config({"disabled_tools": list(DEFAULT_DISABLED_TOOLS)})
    return {
        "disabled_tools": DEFAULT_DISABLED_TOOLS,
        "reset": True,
    }
