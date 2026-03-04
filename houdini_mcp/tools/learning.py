"""Learning-specific tools — screenshot comparison, network export, scene diff.

These tools support an agent's ability to verify its Houdini operations
against expected results using SSIM comparison and scene diffing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain, obtain_list, node_to_dict


@mcp.tool()
def compare_screenshots(image_a: str, image_b: str) -> dict:
    """Compare two images using SSIM (Structural Similarity Index).

    Useful for verifying that a Houdini operation produced the expected
    visual result by comparing viewport/render screenshots.

    Args:
        image_a: Path to the first image file.
        image_b: Path to the second image file.

    Returns:
        Dict with SSIM score (0-1, where 1 = identical) and interpretation.
    """
    from PIL import Image
    from skimage.metrics import structural_similarity as ssim
    import numpy as np

    img_a = np.array(Image.open(image_a).convert("RGB"))
    img_b = np.array(Image.open(image_b).convert("RGB"))

    # Resize to match if different sizes
    if img_a.shape != img_b.shape:
        target_h = min(img_a.shape[0], img_b.shape[0])
        target_w = min(img_a.shape[1], img_b.shape[1])
        img_a = np.array(Image.fromarray(img_a).resize((target_w, target_h)))
        img_b = np.array(Image.fromarray(img_b).resize((target_w, target_h)))

    score = ssim(img_a, img_b, channel_axis=2)

    if score > 0.95:
        interpretation = "Nearly identical"
    elif score > 0.8:
        interpretation = "Very similar"
    elif score > 0.5:
        interpretation = "Somewhat similar"
    else:
        interpretation = "Significantly different"

    return {
        "ssim_score": round(score, 4),
        "interpretation": interpretation,
        "image_a": image_a,
        "image_b": image_b,
    }


@mcp.tool()
def export_node_network(path: str, output_path: str) -> dict:
    """Export the node network structure at a given path to a JSON file.

    Captures the full node graph including positions, connections, and parameter
    values. Useful for recording a learned network configuration as a skill.

    Args:
        path: Root node path to export from (e.g. '/obj/geo1').
        output_path: File path to save the JSON export.

    Returns:
        Dict with export statistics.
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")

    network = _export_node_recursive(node)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(network, f, indent=2, ensure_ascii=False)

    return {
        "exported_from": path,
        "output_path": output_path,
        "total_nodes": _count_nodes(network),
    }


def _export_node_recursive(node, max_depth=10) -> dict:
    """Recursively export node data."""
    if max_depth <= 0:
        return {"path": obtain(node.path()), "truncated": True}

    info = node_to_dict(node)

    # Add non-default parameter values
    params = {}
    for parm in node.parms():
        try:
            if not obtain(parm.isAtDefault()):
                params[obtain(parm.name())] = obtain(parm.eval())
        except Exception:
            pass
    if params:
        info["parameters"] = params

    # Add connections
    inputs = []
    for i, inp in enumerate(node.inputs()):
        if inp is not None:
            inputs.append({
                "index": i,
                "from": obtain(inp.path()),
            })
    if inputs:
        info["inputs"] = inputs

    # Recurse into children
    children = []
    for child in node.children():
        children.append(_export_node_recursive(child, max_depth - 1))
    if children:
        info["children"] = children

    return info


def _count_nodes(network: dict) -> int:
    """Count total nodes in an exported network."""
    count = 1
    for child in network.get("children", []):
        count += _count_nodes(child)
    return count


@mcp.tool()
def get_scene_diff(state_before: str, state_after: str) -> dict:
    """Compare two exported scene states (JSON files) to see what changed.

    Use export_node_network to create before/after snapshots, then this tool
    to understand what the agent's operations actually changed.

    Args:
        state_before: Path to the 'before' JSON export.
        state_after: Path to the 'after' JSON export.

    Returns:
        Dict describing added, removed, and modified nodes.
    """
    with open(state_before, "r", encoding="utf-8") as f:
        before = json.load(f)
    with open(state_after, "r", encoding="utf-8") as f:
        after = json.load(f)

    before_paths = _collect_paths(before)
    after_paths = _collect_paths(after)

    added = sorted(after_paths.keys() - before_paths.keys())
    removed = sorted(before_paths.keys() - after_paths.keys())

    modified = []
    for path in sorted(before_paths.keys() & after_paths.keys()):
        b = before_paths[path]
        a = after_paths[path]
        changes = _diff_node(b, a)
        if changes:
            modified.append({"path": path, "changes": changes})

    return {
        "added_nodes": added,
        "removed_nodes": removed,
        "modified_nodes": modified,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
        },
    }


def _collect_paths(network: dict, result: dict | None = None) -> dict:
    """Flatten a network tree into a dict keyed by path."""
    if result is None:
        result = {}
    path = network.get("path")
    if path:
        result[path] = network
    for child in network.get("children", []):
        _collect_paths(child, result)
    return result


def _diff_node(before: dict, after: dict) -> list[dict]:
    """Compare two node dicts and return list of changes."""
    changes = []

    # Compare parameters
    b_params = before.get("parameters", {})
    a_params = after.get("parameters", {})

    for key in set(b_params.keys()) | set(a_params.keys()):
        b_val = b_params.get(key)
        a_val = a_params.get(key)
        if b_val != a_val:
            changes.append({
                "type": "parameter_changed",
                "name": key,
                "before": b_val,
                "after": a_val,
            })

    # Compare connections
    b_inputs = before.get("inputs", [])
    a_inputs = after.get("inputs", [])
    if b_inputs != a_inputs:
        changes.append({
            "type": "connections_changed",
            "before": b_inputs,
            "after": a_inputs,
        })

    return changes
