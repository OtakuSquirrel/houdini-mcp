"""Entry point: python -m houdini_mcp"""

from houdini_mcp.server import mcp


def main():
    mcp.run()


if __name__ == "__main__":
    main()
