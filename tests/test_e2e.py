"""End-to-end smoke test: start Houdini, connect, operate, stop.

Run with: python tests/test_e2e.py
"""

import asyncio
import sys
import time

# Add parent to path for imports
sys.path.insert(0, ".")

from houdini_mcp.server import mcp


async def call(tool_name: str, **kwargs):
    """Call an MCP tool and print the result."""
    print(f"\n{'='*60}")
    print(f">>> {tool_name}({kwargs})")
    print(f"{'='*60}")
    try:
        result = await mcp.call_tool(tool_name, kwargs)
        # FastMCP 3.x returns list of content objects
        for item in result:
            print(item.text if hasattr(item, 'text') else item)
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return None


async def main():
    print("=" * 60)
    print("  Houdini MCP — E2E Test")
    print("=" * 60)

    # Step 1: Check status
    await call("get_houdini_status")

    # Step 2: Ensure Houdini is ready (will start if needed)
    print("\n--- Starting Houdini (this may take up to 60s) ---")
    result = await call("ensure_houdini_ready")
    if result is None:
        print("FAILED to start Houdini. Aborting.")
        return

    # Step 3: Scene summary
    await call("get_scene_summary")

    # Step 4: Create a new scene
    await call("new_scene")

    # Step 5: Create a geometry node
    await call("create_node", parent_path="/obj", node_type="geo", name="test_geo")

    # Step 6: Create a sphere inside it
    await call("create_node", parent_path="/obj/test_geo", node_type="sphere", name="my_sphere")

    # Step 7: Get node info
    await call("get_node_info", path="/obj/test_geo/my_sphere")

    # Step 8: Get parameter template (discover what params exist)
    await call("get_parm_template", node_path="/obj/test_geo/my_sphere")

    # Step 9: Set a parameter
    await call("set_parameter", node_path="/obj/test_geo/my_sphere", parm_name="rad", value=[2.0, 2.0, 2.0])

    # Step 10: Get geometry info
    await call("get_geometry_info", path="/obj/test_geo/my_sphere")

    # Step 11: Get node tree
    await call("get_node_tree", path="/obj", depth=3)

    # Step 12: Check for errors
    await call("get_node_errors")

    print("\n" + "=" * 60)
    print("  E2E TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
