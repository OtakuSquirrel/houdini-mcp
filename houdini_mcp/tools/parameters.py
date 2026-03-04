"""Parameter tools — get, set, template introspection."""

from __future__ import annotations

from typing import Any

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain, obtain_list, parm_template_to_dict


@mcp.tool()
def get_parameter(node_path: str, parm_name: str) -> dict:
    """Read a parameter value from a node.

    Args:
        node_path: Full path of the node (e.g. '/obj/geo1/sphere1').
        parm_name: Parameter name (e.g. 'tx', 'rad', 'scale').

    Returns:
        Dict with parameter name, value, and expression (if any).
    """
    hou = houdini.hou
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")

    parm = node.parm(parm_name)
    if parm is None:
        # Try as a parm tuple (e.g. 't' for tx/ty/tz)
        parm_tuple = node.parmTuple(parm_name)
        if parm_tuple is not None:
            values = obtain_list(parm_tuple.eval())
            return {
                "name": parm_name,
                "value": values,
                "is_tuple": True,
            }
        raise ValueError(f"Parameter not found: {parm_name} on {node_path}")

    result: dict[str, Any] = {
        "name": parm_name,
        "value": obtain(parm.eval()),
    }

    # Check for expression
    try:
        expr = obtain(parm.expression())
        if expr:
            result["expression"] = expr
            result["expression_language"] = obtain(str(parm.expressionLanguage()))
    except Exception:
        pass

    # Check if it's at default
    try:
        result["is_default"] = obtain(parm.isAtDefault())
    except Exception:
        pass

    return result


@mcp.tool()
def set_parameter(node_path: str, parm_name: str, value: Any) -> dict:
    """Set a parameter value on a node.

    Args:
        node_path: Full path of the node.
        parm_name: Parameter name (e.g. 'tx', 'rad', 'scale').
        value: New value. For tuples, pass a list (e.g. [1.0, 2.0, 3.0] for position).

    Returns:
        Dict confirming the set value.
    """
    hou = houdini.hou
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")

    # Try single parm first
    parm = node.parm(parm_name)
    if parm is not None:
        parm.set(value)
        return {
            "node": node_path,
            "parameter": parm_name,
            "value": obtain(parm.eval()),
        }

    # Try parm tuple
    parm_tuple = node.parmTuple(parm_name)
    if parm_tuple is not None:
        if isinstance(value, (list, tuple)):
            parm_tuple.set(value)
        else:
            parm_tuple.set([value] * obtain(len(parm_tuple)))
        return {
            "node": node_path,
            "parameter": parm_name,
            "value": obtain_list(parm_tuple.eval()),
            "is_tuple": True,
        }

    raise ValueError(f"Parameter not found: {parm_name} on {node_path}")


@mcp.tool()
def get_parm_template(node_path: str) -> list[dict]:
    """Get the parameter template (schema) of a node — names, types, defaults, ranges.

    This is essential for discovering what parameters a node has
    without relying on pre-trained knowledge (which is unreliable for Houdini).

    Args:
        node_path: Full path of the node.

    Returns:
        List of parameter template dicts.
    """
    hou = houdini.hou
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")

    templates = []
    parm_template_group = node.parmTemplateGroup()
    for template in parm_template_group.entries():
        templates.append(parm_template_to_dict(template))
        # If it's a folder, also get its children
        try:
            for child_template in template.parmTemplates():
                child_dict = parm_template_to_dict(child_template)
                child_dict["folder"] = obtain(template.label())
                templates.append(child_dict)
        except Exception:
            pass

    return templates
