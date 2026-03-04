"""Scene management tools — new, save, open, summary."""

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain


@mcp.tool()
def new_scene() -> str:
    """Create a new empty Houdini scene, clearing the current one."""
    hou = houdini.hou
    hou.hipFile.clear(suppress_save_prompt=True)
    return "New scene created."


@mcp.tool()
def save_hip(path: str) -> str:
    """Save the current scene to a .hip file.

    Args:
        path: File path to save to (e.g. 'D:/projects/scene.hip').
    """
    hou = houdini.hou
    hou.hipFile.save(file_name=path)
    return f"Scene saved to {path}"


@mcp.tool()
def open_hip(path: str) -> str:
    """Open a .hip file, replacing the current scene.

    Args:
        path: File path of the .hip file to open.
    """
    hou = houdini.hou
    hou.hipFile.load(file_name=path, suppress_save_prompt=True)
    return f"Opened {path}"


@mcp.tool()
def get_scene_summary() -> dict:
    """Get a summary of the current Houdini scene.

    Returns info about the scene file, frame range, and top-level node counts.
    """
    hou = houdini.hou
    hip_path = obtain(hou.hipFile.path())
    has_unsaved = obtain(hou.hipFile.hasUnsavedChanges())

    fps = obtain(hou.fps())
    frame_range = [obtain(hou.playbar.playbackRange()[0]),
                   obtain(hou.playbar.playbackRange()[1])]
    current_frame = obtain(hou.frame())

    # Count top-level nodes per context
    contexts = {}
    for category_name in ["Object", "Sop", "Driver", "Shop", "Vop", "Cop2", "Chop", "Top", "Lop"]:
        try:
            root_path = "/" + category_name.lower()
            if category_name == "Object":
                root_path = "/obj"
            elif category_name == "Driver":
                root_path = "/out"
            elif category_name == "Shop":
                root_path = "/shop"
            elif category_name == "Vop":
                root_path = "/mat"
            elif category_name == "Cop2":
                root_path = "/img"
            elif category_name == "Chop":
                root_path = "/ch"
            elif category_name == "Top":
                root_path = "/tasks"
            elif category_name == "Lop":
                root_path = "/stage"

            node = hou.node(root_path)
            if node is not None:
                count = obtain(len(node.children()))
                if count > 0:
                    contexts[root_path] = count
        except Exception:
            pass

    return {
        "hip_file": hip_path,
        "has_unsaved_changes": has_unsaved,
        "fps": fps,
        "frame_range": frame_range,
        "current_frame": current_frame,
        "node_counts_by_context": contexts,
    }
