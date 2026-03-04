"""Viewport tools — screenshot, camera settings.

NOTE: Viewport operations require Houdini to be running in GUI mode.
These are marked as experimental — for headless operation, use render tools instead.
"""

from __future__ import annotations

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain


@mcp.tool()
def viewport_screenshot(
    output_path: str,
    width: int = 1920,
    height: int = 1080,
) -> dict:
    """Take a screenshot of the current Houdini viewport.

    EXPERIMENTAL: Requires Houdini running in GUI mode with a visible viewport.
    For headless rendering, use render_frame or render_preview instead.

    Args:
        output_path: File path to save the screenshot (e.g. 'D:/screenshots/viewport.png').
        width: Image width in pixels (default 1920).
        height: Image height in pixels (default 1080).

    Returns:
        Dict with output path and dimensions.
    """
    hou = houdini.hou

    # Get the current desktop and viewport
    try:
        desktop = hou.ui.curDesktop()
        viewport = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
        if viewport is None:
            raise ValueError("No SceneViewer pane found. Houdini must be in GUI mode.")
    except Exception as e:
        raise ValueError(
            f"Cannot access viewport. Houdini must be running in GUI mode. Error: {e}"
        )

    # Use flipbook to capture the viewport
    try:
        flipbook_settings = viewport.flipbookSettings()
        flipbook_settings.frameRange((obtain(hou.frame()), obtain(hou.frame())))
        flipbook_settings.output(output_path)
        flipbook_settings.resolution((width, height))
        viewport.flipbook(flipbook_settings)
    except Exception as e:
        raise ValueError(f"Failed to capture viewport screenshot: {e}")

    return {
        "output_path": output_path,
        "width": width,
        "height": height,
    }


@mcp.tool()
def set_viewport(
    camera: str | None = None,
    display_mode: str | None = None,
) -> dict:
    """Configure viewport settings.

    EXPERIMENTAL: Requires Houdini running in GUI mode.

    Args:
        camera: Path to a camera node to look through (e.g. '/obj/cam1'), or None.
        display_mode: One of 'wireframe', 'smooth', 'smooth_wire', 'hidden_line', or None.

    Returns:
        Dict confirming the applied settings.
    """
    hou = houdini.hou

    try:
        desktop = hou.ui.curDesktop()
        scene_viewer = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
        if scene_viewer is None:
            raise ValueError("No SceneViewer pane found.")
        viewport = scene_viewer.curViewport()
    except Exception as e:
        raise ValueError(f"Cannot access viewport: {e}")

    result = {}

    if camera is not None:
        cam_node = hou.node(camera)
        if cam_node is None:
            raise ValueError(f"Camera node not found: {camera}")
        viewport.setCamera(cam_node)
        result["camera"] = camera

    if display_mode is not None:
        mode_map = {
            "wireframe": hou.glShadingType.Wire,
            "smooth": hou.glShadingType.SmoothShaded,
            "smooth_wire": hou.glShadingType.SmoothWire,
            "hidden_line": hou.glShadingType.HiddenLine,
        }
        gl_mode = mode_map.get(display_mode)
        if gl_mode is None:
            raise ValueError(
                f"Unknown display_mode: {display_mode}. "
                f"Use: {', '.join(mode_map.keys())}"
            )
        viewport.changeShadingMode(gl_mode)
        result["display_mode"] = display_mode

    if not result:
        result["message"] = "No settings changed (no arguments provided)."

    return result
