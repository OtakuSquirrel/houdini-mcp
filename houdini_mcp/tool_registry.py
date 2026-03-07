"""Tool registry — static metadata for all MCP tools.

Provides tool-to-category mapping, descriptions, and default enabled/disabled state.
Used by the middleware guard and WebUI tools management page.
"""

from __future__ import annotations

# Category definitions: description + tools with descriptions
CATEGORY_DEFS: dict[str, dict] = {
    "Scene": {
        "desc": "Create, open, save scenes and get scene info",
        "tools": {
            "new_scene": "Create a new empty scene",
            "save_hip": "Save current scene to .hip file",
            "open_hip": "Open a .hip file",
            "get_scene_summary": "Get scene file, frame range, node counts",
        },
    },
    "Nodes": {
        "desc": "Create, delete, inspect nodes and traverse the node tree",
        "tools": {
            "create_node": "Create a new node inside a parent network",
            "delete_node": "Delete a node by path",
            "get_node_info": "Get detailed info (type, parms, inputs/outputs)",
            "get_node_tree": "Get hierarchical node tree from a path",
            "get_node_children": "Get direct children of a node",
        },
    },
    "Parameters": {
        "desc": "Read, write, and discover node parameters",
        "tools": {
            "get_parameter": "Read a parameter value",
            "set_parameter": "Set a parameter value",
            "get_parm_template": "Get parameter schema (names, types, defaults)",
        },
    },
    "Connections": {
        "desc": "Wire and unwire node connections",
        "tools": {
            "connect_nodes": "Wire output of one node to input of another",
            "disconnect_nodes": "Disconnect an input on a node",
            "get_connections": "Get all input/output connections for a node",
        },
    },
    "Execution": {
        "desc": "Run Python code in Houdini, cook nodes, check errors",
        "tools": {
            "execute_python": "Execute Python code inside Houdini process",
            "cook_node": "Force cook a node and return status",
            "get_node_errors": "Get errors and warnings from nodes",
        },
    },
    "Geometry": {
        "desc": "Inspect geometry data: points, primitives, attributes",
        "tools": {
            "get_geometry_info": "Get point/prim counts and attribute list",
            "get_point_positions": "Get point positions from geometry",
            "get_attribute_values": "Get attribute values (P, N, Cd, etc.)",
        },
    },
    "Viewport": {
        "desc": "Viewport screenshots and display settings",
        "tools": {
            "viewport_screenshot": "Screenshot the current viewport",
            "set_viewport": "Configure viewport camera and display mode",
        },
    },
    "Render": {
        "desc": "Render frames via ROP nodes or quick OpenGL preview",
        "tools": {
            "render_frame": "Render a frame using a ROP node",
            "render_preview": "Quick OpenGL preview render",
        },
    },
    "Verification": {
        "desc": "Compare screenshots, export/diff node networks",
        "tools": {
            "compare_screenshots": "Compare two images via SSIM",
            "export_node_network": "Export node network structure to JSON",
            "get_scene_diff": "Compare two exported scene states",
        },
    },
    "Lifecycle": {
        "desc": "Start/stop Houdini, install startup hooks, check status",
        "tools": {
            "install_startup_scripts": "Install MCP startup hook into Houdini",
            "uninstall_startup_scripts": "Remove MCP startup hook",
            "get_houdini_status": "Check Houdini process and connection status",
            "start_houdini": "Launch Houdini and wait for RPyC",
            "stop_houdini": "Stop the Houdini process",
            "ensure_houdini_ready": "Start Houdini if not running, idempotent",
            "warm_pool": "Batch-launch idle Houdini instances into the pool",
            "is_houdini_healthy": "Check if Houdini is responsive (never hangs)",
        },
    },
    "Screen": {
        "desc": "Capture Houdini windows, desktop, check process status",
        "tools": {
            "capture_houdini_windows": "Screenshot all Houdini windows",
            "capture_screen": "Screenshot desktop or specific region",
            "get_houdini_windows": "List Houdini window positions and sizes",
            "check_process_status": "Check if Houdini process is running",
        },
    },
    "Events": {
        "desc": "Monitor node operations (create, delete, parm changes). Disabled by default — may cause save issues with large scenes",
        "tools": {
            "start_event_monitoring": "Install event listeners on all contexts",
            "stop_event_monitoring": "Remove all event listeners",
            "get_event_log": "Retrieve recent operation events",
            "get_event_monitoring_status": "Check if monitoring is active",
        },
    },
    "Sessions": {
        "desc": "Manage MCP sessions, ports, multi-instance connections",
        "tools": {
            "list_all_sessions": "List all registered MCP sessions",
            "disconnect_houdini": "Disconnect from current Houdini instance",
            "get_current_session": "Get this MCP server's session info",
            "cleanup_stale_sessions": "Remove sessions with dead processes",
            "scan_ports": "Scan port range for Houdini/MCP status",
            "get_pool_status": "Show idle/active Houdini instance counts",
            "acquire_from_pool": "Grab an idle instance and connect to it",
            "adopt_idle": "Kill stuck Houdini, adopt an idle replacement",
            "get_mcp_config": "Get MCP configuration",
            "update_mcp_config": "Update MCP configuration",
            "connect_to_houdini": "Connect to a Houdini instance on a port",
            "switch_active_houdini": "Switch which Houdini receives commands",
            "list_houdini_connections": "List all managed Houdini connections",
        },
    },
}

# Flatten for backward compat
TOOL_CATEGORIES: dict[str, list[str]] = {
    cat: list(info["tools"].keys()) for cat, info in CATEGORY_DEFS.items()
}

# Tools disabled by default (event monitoring has known bugs with saving)
DEFAULT_DISABLED_TOOLS: list[str] = [
    "capture_screen",
    "start_event_monitoring",
    "stop_event_monitoring",
    "get_event_log",
    "get_event_monitoring_status",
]

# Build reverse mapping: tool_name → category
TOOL_TO_CATEGORY: dict[str, str] = {}
ALL_TOOL_NAMES: set[str] = set()
TOOL_DESCRIPTIONS: dict[str, str] = {}
for _cat, _info in CATEGORY_DEFS.items():
    for _tool, _desc in _info["tools"].items():
        TOOL_TO_CATEGORY[_tool] = _cat
        ALL_TOOL_NAMES.add(_tool)
        TOOL_DESCRIPTIONS[_tool] = _desc


def get_disabled_tools() -> list[str]:
    """Get the current list of disabled tools from config.

    Falls back to DEFAULT_DISABLED_TOOLS if not set in config.
    """
    from houdini_mcp.config import load_config
    config = load_config()
    return config.get("disabled_tools", list(DEFAULT_DISABLED_TOOLS))


def is_tool_enabled(tool_name: str) -> bool:
    """Check if a specific tool is enabled."""
    return tool_name not in get_disabled_tools()
