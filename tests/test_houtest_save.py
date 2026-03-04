"""Start hython, build a small test scene, save to houtest/."""

import asyncio
import json
import sys

sys.path.insert(0, ".")

from houdini_mcp.server import mcp


async def call(tool_name, **kwargs):
    """Call an MCP tool and print the result cleanly."""
    print(f"  >>> {tool_name}({kwargs})")
    try:
        result = await mcp.call_tool(tool_name, kwargs)
        # result is a CallToolResult; access .content for list of TextContent
        if hasattr(result, "content"):
            items = result.content
        else:
            # fallback: iterate to find content
            items = []
            for field_name, field_val in result:
                if field_name == "content" and isinstance(field_val, list):
                    items = field_val
                    break

        for item in items:
            if hasattr(item, "text"):
                try:
                    data = json.loads(item.text)
                    print(f"      => {json.dumps(data, indent=2, ensure_ascii=False)}")
                    return data
                except json.JSONDecodeError:
                    print(f"      => {item.text}")
                    return item.text
        return None
    except Exception as e:
        print(f"      ERROR: {e}")
        return None


async def main():
    import tempfile
    from pathlib import Path
    _test_dir = Path(tempfile.gettempdir()) / "houdini_mcp_tests"
    _test_dir.mkdir(parents=True, exist_ok=True)
    save_path = str(_test_dir / "test_scene.hip")

    print("=" * 60)
    print("  HOUTEST - Build & Save Scene (hython mode)")
    print("=" * 60)

    # 1. Start hython
    print("\n[1] Starting Houdini (hython mode)...")
    r = await call("start_houdini", mode="hython", timeout=30)
    if not r:
        print("FAILED to start houdini")
        return
    print(f"    Status: {r.get('status')}, Connected: {r.get('rpyc_connected')}")

    # 2. New scene
    print("\n[2] New scene...")
    await call("new_scene")

    # 3. Create a geo node with a sphere inside
    print("\n[3] Creating /obj/my_sphere (geo container)...")
    await call("create_node", parent_path="/obj", node_type="geo", name="my_sphere")

    print("    Creating sphere SOP inside...")
    await call("create_node", parent_path="/obj/my_sphere", node_type="sphere", name="sphere1")

    # 4. Set sphere parameters - make it bigger and more detailed
    print("\n[4] Setting sphere parameters...")
    await call("set_parameter", node_path="/obj/my_sphere/sphere1", parm_name="rad", value=[2.0, 2.0, 2.0])
    await call("set_parameter", node_path="/obj/my_sphere/sphere1", parm_name="rows", value=24)
    await call("set_parameter", node_path="/obj/my_sphere/sphere1", parm_name="cols", value=24)

    # 5. Create a transform SOP and connect it
    print("\n[5] Creating transform SOP...")
    await call("create_node", parent_path="/obj/my_sphere", node_type="xform", name="transform1")
    await call("connect_nodes",
               from_path="/obj/my_sphere/sphere1", from_output=0,
               to_path="/obj/my_sphere/transform1", to_input=0)
    await call("set_parameter", node_path="/obj/my_sphere/transform1", parm_name="ty", value=1.5)

    # 6. Create a color SOP
    print("\n[6] Creating color SOP...")
    await call("create_node", parent_path="/obj/my_sphere", node_type="color", name="color1")
    await call("connect_nodes",
               from_path="/obj/my_sphere/transform1", from_output=0,
               to_path="/obj/my_sphere/color1", to_input=0)
    await call("set_parameter", node_path="/obj/my_sphere/color1", parm_name="colorr", value=0.2)
    await call("set_parameter", node_path="/obj/my_sphere/color1", parm_name="colorg", value=0.6)
    await call("set_parameter", node_path="/obj/my_sphere/color1", parm_name="colorb", value=1.0)

    # 7. Create a null as output
    print("\n[7] Creating OUT null...")
    await call("create_node", parent_path="/obj/my_sphere", node_type="null", name="OUT")
    await call("connect_nodes",
               from_path="/obj/my_sphere/color1", from_output=0,
               to_path="/obj/my_sphere/OUT", to_input=0)

    # 8. Set display flag on OUT
    print("\n[8] Setting display/render flags on OUT...")
    await call("execute_python", code="hou.node('/obj/my_sphere/OUT').setDisplayFlag(True)")
    await call("execute_python", code="hou.node('/obj/my_sphere/OUT').setRenderFlag(True)")

    # 9. Check geometry
    print("\n[9] Geometry info on OUT:")
    await call("get_geometry_info", path="/obj/my_sphere/OUT")

    # 10. Check node tree
    print("\n[10] Final node tree:")
    await call("get_node_tree", path="/obj", depth=3)

    # 11. Check errors
    print("\n[11] Error check:")
    await call("get_node_errors")

    # 12. Save
    print(f"\n[12] Saving to {save_path}...")
    await call("save_hip", path=save_path)

    # 13. Scene summary
    print("\n[13] Final scene summary:")
    await call("get_scene_summary")

    # 14. Stop
    print("\n[14] Stopping Houdini...")
    await call("stop_houdini", force=True)

    print("\n" + "=" * 60)
    print(f"  DONE - saved to {save_path}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
