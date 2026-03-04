"""Geometry inspection tools — info, point positions, attribute values."""

from __future__ import annotations

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain, obtain_list, format_vector


@mcp.tool()
def get_geometry_info(path: str) -> dict:
    """Get geometry information for a SOP node — point/prim counts, attribute list.

    Args:
        path: Full path to a SOP node (e.g. '/obj/geo1/sphere1').

    Returns:
        Dict with point count, primitive count, vertex count, and attribute lists.
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")

    geo = node.geometry()
    if geo is None:
        raise ValueError(f"Node has no geometry output: {path}")

    def attrib_info(attrib):
        return {
            "name": obtain(attrib.name()),
            "type": obtain(str(attrib.dataType())),
            "size": obtain(attrib.size()),
        }

    result = {
        "node": path,
        "num_points": obtain(len(geo.points())),
        "num_prims": obtain(len(geo.prims())),
        "bounding_box": {
            "min": format_vector(geo.boundingBox().minvec()),
            "max": format_vector(geo.boundingBox().maxvec()),
        },
        "point_attribs": [attrib_info(a) for a in geo.pointAttribs()],
        "prim_attribs": [attrib_info(a) for a in geo.primAttribs()],
        "detail_attribs": [attrib_info(a) for a in geo.globalAttribs()],
    }
    # vertices() may not exist in all Houdini versions
    try:
        result["num_vertices"] = obtain(len(geo.vertices()))
    except Exception:
        pass
    try:
        result["vertex_attribs"] = [attrib_info(a) for a in geo.vertexAttribs()]
    except Exception:
        pass
    return result


@mcp.tool()
def get_point_positions(path: str, limit: int = 100) -> dict:
    """Get point positions from a SOP node's geometry.

    Args:
        path: Full path to a SOP node.
        limit: Maximum number of points to return (default 100).

    Returns:
        Dict with total point count and a list of [x,y,z] positions.
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")

    geo = node.geometry()
    if geo is None:
        raise ValueError(f"Node has no geometry output: {path}")

    total = obtain(len(geo.points()))
    positions = []
    for i, pt in enumerate(geo.points()):
        if i >= limit:
            break
        positions.append(format_vector(pt.position()))

    return {
        "node": path,
        "total_points": total,
        "returned": len(positions),
        "positions": positions,
    }


@mcp.tool()
def get_attribute_values(
    path: str,
    attrib_name: str,
    attrib_class: str = "point",
    limit: int = 100,
) -> dict:
    """Get attribute values from geometry.

    Args:
        path: Full path to a SOP node.
        attrib_name: Name of the attribute (e.g. 'P', 'N', 'Cd').
        attrib_class: One of 'point', 'prim', 'vertex', 'detail'.
        limit: Maximum number of values to return.

    Returns:
        Dict with attribute info and values.
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")

    geo = node.geometry()
    if geo is None:
        raise ValueError(f"Node has no geometry output: {path}")

    if attrib_class == "detail":
        attrib = geo.findGlobalAttrib(attrib_name)
        if attrib is None:
            raise ValueError(f"Detail attribute not found: {attrib_name}")
        value = obtain(geo.attribValue(attrib_name))
        return {
            "attrib_name": attrib_name,
            "attrib_class": "detail",
            "type": obtain(str(attrib.dataType())),
            "value": value,
        }

    # For point/prim/vertex
    if attrib_class == "point":
        attrib = geo.findPointAttrib(attrib_name)
        elements = geo.points()
    elif attrib_class == "prim":
        attrib = geo.findPrimAttrib(attrib_name)
        elements = geo.prims()
    elif attrib_class == "vertex":
        attrib = geo.findVertexAttrib(attrib_name)
        elements = geo.vertices()
    else:
        raise ValueError(f"Invalid attrib_class: {attrib_class}. Use point/prim/vertex/detail.")

    if attrib is None:
        raise ValueError(f"{attrib_class.title()} attribute not found: {attrib_name}")

    total = obtain(len(elements))
    values = []
    for i, elem in enumerate(elements):
        if i >= limit:
            break
        val = elem.attribValue(attrib_name)
        # Convert tuples/vectors to lists
        if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
            values.append(obtain_list(val))
        else:
            values.append(obtain(val))

    return {
        "attrib_name": attrib_name,
        "attrib_class": attrib_class,
        "type": obtain(str(attrib.dataType())),
        "size": obtain(attrib.size()),
        "total_elements": total,
        "returned": len(values),
        "values": values,
    }
