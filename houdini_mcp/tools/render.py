"""Render tools — render frame via ROP, preview render.

These work with or without a GUI, using ROP nodes for rendering.
"""

from __future__ import annotations

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain


@mcp.tool()
def render_frame(
    rop_path: str,
    frame: float | None = None,
    output: str | None = None,
) -> dict:
    """Render a frame using a ROP (render output) node.

    Args:
        rop_path: Path to the ROP node (e.g. '/out/mantra1', '/out/karma1').
        frame: Frame number to render. If None, renders current frame.
        output: Override output file path. If None, uses the ROP's configured path.

    Returns:
        Dict with render status and output path.
    """
    hou = houdini.hou
    rop = hou.node(rop_path)
    if rop is None:
        raise ValueError(f"ROP node not found: {rop_path}")

    if output is not None:
        # Try to set the output path on the ROP
        parm = rop.parm("vm_picture") or rop.parm("picture") or rop.parm("sopoutput")
        if parm is not None:
            parm.set(output)

    if frame is not None:
        hou.setFrame(frame)

    render_frame_val = frame if frame is not None else obtain(hou.frame())

    # Render the single frame
    rop.render(
        frame_range=(render_frame_val, render_frame_val),
        ignore_inputs=False,
    )

    # Try to get the output path from the ROP
    output_path = None
    for parm_name in ["vm_picture", "picture", "sopoutput"]:
        parm = rop.parm(parm_name)
        if parm is not None:
            output_path = obtain(parm.eval())
            break

    return {
        "rop": rop_path,
        "frame": render_frame_val,
        "output_path": output_path,
        "status": "rendered",
    }


@mcp.tool()
def render_preview(output_path: str, rop_path: str | None = None) -> dict:
    """Quick OpenGL preview render of the current viewport/scene.

    If rop_path is provided, uses that ROP. Otherwise, creates a temporary
    OpenGL ROP for a quick preview.

    Args:
        output_path: File path for the output image (e.g. 'D:/renders/preview.png').
        rop_path: Optional path to an existing OpenGL ROP node.

    Returns:
        Dict with output path and status.
    """
    hou = houdini.hou

    if rop_path is not None:
        rop = hou.node(rop_path)
        if rop is None:
            raise ValueError(f"ROP node not found: {rop_path}")
    else:
        # Create a temporary OpenGL ROP
        out = hou.node("/out")
        rop = out.createNode("opengl", "tmp_preview_render")

    # Set output path
    picture_parm = rop.parm("picture")
    if picture_parm is not None:
        picture_parm.set(output_path)

    current_frame = obtain(hou.frame())
    rop.render(frame_range=(current_frame, current_frame))

    # Clean up temporary ROP
    if rop_path is None:
        rop.destroy()

    return {
        "output_path": output_path,
        "frame": current_frame,
        "status": "rendered",
    }
