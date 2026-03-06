"""Entry point: python -m houdini_mcp.webui

Starts the WebUI management server.
"""

import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Houdini MCP WebUI — management dashboard",
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=8765,
        help="Port to listen on (default: 8765)",
    )
    parser.add_argument(
        "--reload", action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    import uvicorn
    uvicorn.run(
        "houdini_mcp.webui.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
