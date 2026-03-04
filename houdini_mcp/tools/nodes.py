"""Node operation tools — create, delete, info, tree, children."""

from __future__ import annotations

from typing import Any

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain, obtain_list, node_to_dict


@mcp.tool()
def create_node(parent_path: str, node_type: str, name: str | None = None) -> dict:
    """Create a new node inside a parent network.

    Args:
        parent_path: Path to the parent node (e.g. '/obj', '/obj/geo1').
        node_type: Houdini node type name (e.g. 'geo', 'sphere', 'null').
        name: Optional name for the new node.

    Returns:
        Dict with the created node's info.
    """
    hou = houdini.hou
    parent = hou.node(parent_path)
    if parent is None:
        raise ValueError(f"Parent node not found: {parent_path}")

    node = parent.createNode(node_type, node_name=name)
    node.moveToGoodPosition()
    return node_to_dict(node)


@mcp.tool()
def delete_node(path: str) -> str:
    """Delete a node by its path.

    Args:
        path: Full path of the node to delete (e.g. '/obj/geo1').
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")
    node.destroy()
    return f"Deleted node: {path}"


@mcp.tool()
def get_node_info(path: str) -> dict:
    """Get detailed information about a node.

    Args:
        path: Full path of the node (e.g. '/obj/geo1/sphere1').

    Returns:
        Dict with node info including type, parameters, inputs/outputs.
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")

    info = node_to_dict(node)

    # Add input/output info
    inputs = []
    for i, inp in enumerate(node.inputs()):
        if inp is not None:
            inputs.append({
                "index": i,
                "connected_to": obtain(inp.path()),
            })
    info["inputs"] = inputs

    outputs = []
    for conn in node.outputs():
        outputs.append(obtain(conn.path()))
    info["outputs"] = outputs

    # Add parameter count
    info["num_parameters"] = obtain(len(node.parms()))

    # Add display/render flags if applicable
    try:
        info["is_display_flag"] = obtain(node.isDisplayFlagSet())
    except Exception:
        pass
    try:
        info["is_render_flag"] = obtain(node.isRenderFlagSet())
    except Exception:
        pass

    # Add cook state
    try:
        info["is_cooked"] = obtain(node.needsToCook()) is False
    except Exception:
        pass

    # Errors/warnings
    errors = obtain(node.errors())
    warnings = obtain(node.warnings())
    if errors:
        info["errors"] = errors
    if warnings:
        info["warnings"] = warnings

    return info


@mcp.tool()
def get_node_tree(path: str = "/", depth: int = 2) -> dict:
    """Get a hierarchical tree of nodes starting from a path.

    Args:
        path: Root path to start from (default: '/' for entire scene).
        depth: How many levels deep to traverse (default: 2).

    Returns:
        Nested dict representing the node tree.
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")

    return _build_tree(node, depth)


def _build_tree(node: Any, depth: int) -> dict:
    """Recursively build a node tree dict."""
    result = {
        "path": obtain(node.path()),
        "type": obtain(node.type().name()),
        "name": obtain(node.name()),
    }

    if depth > 0:
        children = []
        for child in node.children():
            children.append(_build_tree(child, depth - 1))
        if children:
            result["children"] = children

    return result


@mcp.tool()
def get_node_children(path: str) -> list[dict]:
    """Get the direct children of a node.

    Args:
        path: Full path of the parent node.

    Returns:
        List of dicts, each describing a child node.
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")

    return [node_to_dict(child) for child in node.children()]
