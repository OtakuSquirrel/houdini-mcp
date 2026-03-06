"""Entry point: python -m houdini_mcp

Supports CLI arguments:
  --port PORT        RPyC port to connect to (auto-discovers if omitted)
  --session-id ID    Session ID for this MCP server instance

The MCP server starts in idle mode — it does NOT connect to Houdini
or register a session until a tool is actually invoked by the agent.
This prevents occupying ports when the agent is working on unrelated tasks.
"""

import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Houdini MCP Server — control Houdini via MCP + RPyC",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="RPyC port to connect to (auto-discovers if omitted)",
    )
    parser.add_argument(
        "--session-id", type=str, default=None,
        help="Session ID for this MCP server instance",
    )

    args = parser.parse_args()

    from houdini_mcp.server import mcp, set_port, set_session_id

    # Only set port if explicitly provided — otherwise auto-discover on first tool call
    if args.port is not None:
        set_port(args.port)

    # Pre-set session ID if provided (otherwise generated on first connect)
    if args.session_id is not None:
        set_session_id(args.session_id)

    # Start MCP server in idle mode — no Houdini connection yet.
    # Session registration happens lazily in connection.connect()
    mcp.run()


if __name__ == "__main__":
    main()
