"""Test hython mode: start headless Houdini, run operations, stop."""

import asyncio
import sys

sys.path.insert(0, ".")

from houdini_mcp.server import mcp


async def call(tool_name, **kwargs):
    print(f"\n>>> {tool_name}({kwargs})")
    try:
        result = await mcp.call_tool(tool_name, kwargs)
        for item in result:
            text = item.text if hasattr(item, "text") else str(item)
            print(text[:800])
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return None


async def main():
    print("=" * 60)
    print("  HYTHON MODE TEST")
    print("=" * 60)

    # 1. Status before
    print("\n[1] Pre-launch status:")
    await call("get_houdini_status")

    # 2. Start in hython mode
    print("\n[2] Starting Houdini in HYTHON mode (headless)...")
    await call("start_houdini", mode="hython", timeout=30)

    # 3. Scene operations
    print("\n[3] Scene summary:")
    await call("get_scene_summary")

    print("\n[4] Creating a sphere node:")
    await call("create_node", parent_path="/obj", node_type="geo", name="test_sphere")

    print("\n[5] Node tree:")
    await call("get_node_tree", path="/obj", depth=2)

    print("\n[6] Node errors check:")
    await call("get_node_errors")

    # 4. Stop
    print("\n[7] Stopping Houdini...")
    await call("stop_houdini", force=True)

    print("\n" + "=" * 60)
    print("  HYTHON TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
