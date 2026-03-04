"""Test lifecycle: start Houdini, wait for RPyC, run one operation, stop."""

import asyncio
import sys

sys.path.insert(0, ".")

from houdini_mcp.server import mcp


async def call(tool_name, **kwargs):
    print(f"\n>>> {tool_name}({kwargs})")
    try:
        result = await mcp.call_tool(tool_name, kwargs)
        for item in result:
            text = item.text if hasattr(item, 'text') else str(item)
            print(text[:500])
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return None


async def main():
    print("=== LIFECYCLE TEST ===")

    # Step 1: status check
    await call("get_houdini_status")

    # Step 2: start Houdini with 90s timeout (first startup is slow)
    print("\n--- Starting Houdini (up to 90s) ---")
    await call("ensure_houdini_ready", timeout=90)

    # Step 3: check log file
    from pathlib import Path
    log = Path.home() / "houdini_mcp" / "houdini_startup.log"
    if log.exists():
        print(f"\n--- Startup log ({log}) ---")
        print(log.read_text(encoding="utf-8"))
    else:
        print(f"\n--- No startup log found at {log} ---")

    # Step 4: try a simple operation
    await call("get_scene_summary")

    # Step 5: stop
    await call("stop_houdini")

    print("\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
