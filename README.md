# houdini-mcp

MCP (Model Context Protocol) server for SideFX Houdini. Enables AI assistants
(Claude Code, etc.) to control Houdini via RPyC — creating nodes, setting parameters,
running Python in Houdini's context, capturing viewport screenshots, and more.

Supports **multi-instance**: multiple Houdini sessions on different ports, each
controlled by an independent MCP server. Includes a **WebUI** management dashboard
for configuration, session discovery, and startup script management.

## Architecture

```
┌──────────────────────────────────────────────────┐
│          WebUI Backend (Python/FastAPI)           │
│  Config mgmt | Session discovery | Port monitor  │
└────────────────────┬─────────────────────────────┘
                     │ reads/writes
              ┌──────┴──────┐
              │ Config Store │  ~/houdini_mcp/
              │ config.json  │  sessions/*.json
              └──────┬──────┘
        ┌────────────┼────────────┐
        ▼            ▼            ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │ MCP Srv A│ │ MCP Srv B│ │ MCP Srv C│  (independent)
  │ port 18811│ │ port 18812│ │ port 18813│
  │ Houdini A│ │ Houdini B│ │ Houdini C│
  └──────────┘ └──────────┘ └──────────┘
```

Each MCP server is a 1:1 pair with a Houdini instance. They communicate via
RPyC over TCP (localhost). The MCP server uses stdio transport (FastMCP) to
talk to Claude Code / AI assistants.

The MCP server starts **idle** — it does not connect to Houdini until a tool
is actually invoked. This prevents occupying ports when the agent is working
on unrelated tasks. Port auto-discovery scans the configured range to find
active RPyC listeners.

## Requirements

- Python 3.11+
- SideFX Houdini 20.5 or 21.0
- Windows (screen capture tools use Win32 API; all other tools are cross-platform)

## Installation

```bash
# Clone the repository
git clone https://github.com/<your-org>/houdini-mcp.git
cd houdini-mcp

# Create and activate venv
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

# Install core
pip install -e .

# Install with WebUI support
pip install -e ".[webui]"

# Install dev dependencies (optional, for running tests)
pip install -e ".[dev]"
```

## How to Use

### MCP Server (for Claude Code / AI Agents)

```bash
# Start MCP server (default port 18811)
.venv\Scripts\python.exe -m houdini_mcp

# Start MCP server on a specific port
.venv\Scripts\python.exe -m houdini_mcp --port 18812

# Start with a named session ID
.venv\Scripts\python.exe -m houdini_mcp --port 18812 --session-id my-session

# Show all CLI options
.venv\Scripts\python.exe -m houdini_mcp --help
```

### WebUI Management Dashboard

```bash
# Start WebUI (default: http://127.0.0.1:8765)
.venv\Scripts\python.exe -m houdini_mcp.webui

# Custom host/port
.venv\Scripts\python.exe -m houdini_mcp.webui --host 0.0.0.0 --port 9000

# Auto-reload on code changes (development)
.venv\Scripts\python.exe -m houdini_mcp.webui --reload
```

The WebUI provides:
- **Session list**: view all active Houdini MCP sessions, their ports and PIDs
- **Configuration**: toggle auto-start RPyC for human/agent launches, set port range
- **Startup scripts**: install/uninstall MCP hooks per Houdini version (non-destructive)
- **Process monitor**: see running Houdini/hython processes
- **Port status**: view which ports are in use or available

### Claude Code Configuration

Add to `.claude/settings.local.json` in your project:

```json
{
  "mcpServers": {
    "houdini": {
      "command": "/path/to/houdini-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "houdini_mcp"],
      "cwd": "/path/to/houdini-mcp"
    }
  }
}
```

For multi-instance, specify a port per agent:

```json
{
  "mcpServers": {
    "houdini": {
      "command": "/path/to/houdini-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "houdini_mcp", "--port", "18812"],
      "cwd": "/path/to/houdini-mcp"
    }
  }
}
```

### Quick Start (MCP Tools)

#### 1. Install startup scripts (one-time)

```
install_startup_scripts()
# Non-destructive: copies houdini_mcp_startup.py to Houdini scripts dir
# and injects a one-line hook into 456.py (preserves existing content)
```

Or use the WebUI — click "Install" next to any Houdini version.

#### 2. Launch and control Houdini

```
# Recommended entry point (idempotent, auto-starts if needed)
ensure_houdini_ready()

# Or start explicitly with options
start_houdini(version="21.0", mode="gui")   # GUI mode, auto port
start_houdini(mode="hython", port=18815)     # headless, specific port

# Work with the scene
get_scene_summary()
create_node("/obj", "geo", "mysphere")
set_parameter("/obj/mysphere/sphere1", "rad", 2.0)
get_geometry_info("/obj/mysphere/sphere1")
viewport_screenshot("/tmp/view.png")

# Session management
get_current_session()      # this MCP server's session info
list_all_sessions()        # all sessions on this machine
scan_ports()               # full port range status with PIDs
disconnect_houdini()       # release connection (Houdini RPyC stays alive)
cleanup_stale_sessions()   # remove dead sessions

# Configuration (via MCP tools)
get_mcp_config()
update_mcp_config(human_auto_start=True)   # let human-launched Houdini start RPyC

# Shutdown
stop_houdini()
```

## Multi-Instance Support

Each Houdini instance runs on a unique RPyC port. Ports are dynamically
allocated from a configurable range (default: 18811–18899).

**How it works**:
- `start_houdini()` calls `allocate_port()` to find the next free port
- Launches Houdini with env vars: `HOUDINI_MCP_ENABLED=1`, `HOUDINI_MCP_PORT=<port>`
- The startup script reads these env vars and starts the RPyC listener
- MCP server auto-discovers the RPyC port and connects on first tool call
- Session is registered on connect, unregistered on disconnect or process exit

**Human-launched Houdini** does NOT start RPyC by default (configurable via
WebUI or `update_mcp_config`). Agent-launched Houdini always starts RPyC.

**Disconnect without killing Houdini**: `disconnect_houdini()` releases the
MCP connection while keeping Houdini's RPyC listener alive. Another agent
can connect to the same Houdini later.

## Available Tools (50 total)

| Category | Tools | Count |
|---|---|---|
| **Lifecycle** | `install_startup_scripts`, `uninstall_startup_scripts`, `get_houdini_status`, `start_houdini`, `stop_houdini`, `ensure_houdini_ready` | 6 |
| **Sessions** | `list_all_sessions`, `get_current_session`, `disconnect_houdini`, `cleanup_stale_sessions`, `scan_ports`, `get_mcp_config`, `update_mcp_config` | 7 |
| **Scene** | `new_scene`, `save_hip`, `open_hip`, `get_scene_summary` | 4 |
| **Nodes** | `create_node`, `delete_node`, `get_node_info`, `get_node_tree`, `get_node_children` | 5 |
| **Parameters** | `get_parameter`, `set_parameter`, `get_parm_template` | 3 |
| **Connections** | `connect_nodes`, `disconnect_nodes`, `get_connections` | 3 |
| **Execution** | `execute_python`, `cook_node`, `get_node_errors` | 3 |
| **Geometry** | `get_geometry_info`, `get_point_positions`, `get_attribute_values` | 3 |
| **Viewport** | `viewport_screenshot`, `set_viewport` | 2 |
| **Render** | `render_frame`, `render_preview` | 2 |
| **Verification** | `compare_screenshots`, `export_node_network`, `get_scene_diff` | 3 |
| **Screen** | `capture_houdini_windows`, `capture_screen`, `get_houdini_windows`, `check_process_status` | 4 |
| **Events** | `start_event_monitoring`, `stop_event_monitoring`, `get_event_log`, `get_event_monitoring_status` | 4 |

## Project Structure

```
houdini-mcp/
├── houdini_mcp/                  # MCP server package
│   ├── __main__.py               # Entry point: python -m houdini_mcp
│   ├── server.py                 # FastMCP instance + global HoudiniConnection
│   ├── connection.py             # RPyC connection manager (auto-reconnect)
│   ├── config.py                 # Config management (~/houdini_mcp/config.json)
│   ├── registry.py               # Session registry (~/houdini_mcp/sessions/)
│   ├── utils.py                  # RPyC netref → native Python conversion
│   ├── tools/                    # Tool modules (each registers @mcp.tool)
│   │   ├── lifecycle.py          # Start/stop/status, startup script install
│   │   ├── sessions.py           # Session & config management tools
│   │   ├── scene.py              # New/save/open scenes
│   │   ├── nodes.py              # Create/delete/inspect nodes
│   │   ├── parameters.py         # Get/set node parameters
│   │   ├── connections.py        # Wire/unwire node connections
│   │   ├── execution.py          # Execute Python code, cook nodes
│   │   ├── geometry.py           # Inspect geometry data
│   │   ├── viewport.py           # Viewport screenshot, camera control
│   │   ├── render.py             # ROP rendering
│   │   ├── verification.py       # SSIM image comparison, scene diff
│   │   ├── screen.py             # Win32 window capture
│   │   └── events.py             # Scene event monitoring
│   └── webui/                    # WebUI management dashboard
│       ├── __main__.py           # Entry point: python -m houdini_mcp.webui
│       ├── app.py                # FastAPI application
│       ├── routes/               # API route modules
│       │   ├── config_routes.py  # Config CRUD
│       │   ├── session_routes.py # Session discovery/management
│       │   └── houdini_routes.py # Houdini version/process discovery
│       └── static/               # Frontend assets
│           ├── index.html        # Dashboard (sessions + processes)
│           └── config.html       # Configuration page
├── houdini_plugin/
│   └── houdini_mcp_startup.py    # Source of truth (deployed to Houdini prefs)
├── tests/                        # Integration tests
├── pyproject.toml                # Package config & dependencies
└── .venv/                        # Virtual environment (not tracked)
```

## Configuration

Configuration is stored at `~/houdini_mcp/config.json`:

```json
{
  "human_launch": {
    "auto_start_rpyc": false
  },
  "agent_launch": {
    "auto_start_rpyc": true
  },
  "port_range": [18811, 18899]
}
```

- **human_launch.auto_start_rpyc**: Whether manually opened Houdini starts RPyC (default: `false`)
- **agent_launch.auto_start_rpyc**: Whether agent-launched Houdini starts RPyC (default: `true`)
- **port_range**: Port range for dynamic allocation (default: `18811–18899`)

Edit via WebUI, MCP tool (`update_mcp_config`), or directly.

## Environment Variables

The startup script (`houdini_mcp_startup.py`) reads these env vars
(set automatically by `start_houdini()`, or set manually):

| Variable | Values | Default |
|---|---|---|
| `HOUDINI_MCP_ENABLED` | `"1"` to start RPyC, `"0"` to skip | Check config |
| `HOUDINI_MCP_PORT` | Port number or `"auto"` | `"auto"` |

## Houdini Version Support

| | Houdini 20.5 | Houdini 21.0 |
|---|---|---|
| Embedded Python | 3.10 | 3.11 |
| RPyC | 4.x | 4.1.0 |
| `hrpyc` module | Yes | Yes |
| Prefs dir | `~/Documents/houdini20.5/` | `~/Documents/houdini21.0/` |
| Status | Supported | Supported |

Houdini installations are auto-detected from
`C:/Program Files/Side Effects Software/`. Use `start_houdini(version="20.5")`
to select a specific version, or omit `version` to use the latest.

## How It Works

Houdini ships `hrpyc` (an RPyC server wrapper bundled with Houdini). The startup
script (`houdini_plugin/houdini_mcp_startup.py`) is deployed to
`~/Documents/houdiniX.Y/scripts/` via `install_startup_scripts`. It is installed
as a **separate file** alongside `456.py`, with a single hook line injected into
`456.py` — existing content is fully preserved (non-destructive).

When Houdini starts, the hook runs our script, which:
1. Checks env vars and config to decide whether to start RPyC
2. Allocates a free port (or uses the one specified via env var)
3. Calls `hrpyc.start_server(port=<port>)` to start the RPyC listener
4. Installs event monitoring callbacks (deferred until UI is ready)

The startup script does **not** register sessions or start MCP servers — it
only starts the RPyC listener. Session registration happens lazily when the
MCP server actually connects.

The MCP server starts idle (via `.mcp.json`). When an agent calls a Houdini
tool, it auto-discovers the RPyC port, connects with
`rpyc.classic.connect("localhost", <port>)`, registers the session, and
accesses the full `hou` module remotely via `conn.modules.hou`.

> **RPyC version pinning**: Houdini 20.5 and 21.0 both ship `rpyc` 4.x internally.
> This package pins `rpyc>=4.1,<5` — RPyC 6.x has an incompatible wire protocol.

## Running Tests

With Houdini installed and accessible:

```bash
# From the houdini-mcp directory:
python tests/test_e2e.py           # full pipeline (GUI mode)
python tests/test_hython.py        # headless hython mode
python tests/test_lifecycle.py     # start/stop/reconnect
python tests/test_houtest_save.py  # build and save a test scene
```

Test output (.hip files) goes to the system temp directory
(`%TEMP%/houdini_mcp_tests/` on Windows).

## Troubleshooting

**RPyC connection refused**
- Ensure startup scripts are installed: call `install_startup_scripts()` or use WebUI
- Restart Houdini after installing scripts
- Check `~/houdini_mcp/houdini_startup.log` for errors
- For agent-launched Houdini, check that `HOUDINI_MCP_ENABLED=1` is set

**Port conflicts**
- Use `list_all_sessions()` or WebUI to see which ports are in use
- Run `cleanup_stale_sessions()` to remove dead sessions
- Adjust `port_range` in config if you need more ports

**Wrong RPyC version**
- This server requires `rpyc>=4.1,<5`. Check with `pip show rpyc`.
- RPyC 6.x has an incompatible protocol and will cause connection errors.

**Houdini not found**
- Default search path: `C:/Program Files/Side Effects Software/`
- Install Houdini to the default path, or check the `installed_versions` field
  from `get_houdini_status()`.

**Viewport screenshot fails**
- Requires GUI mode (`start_houdini(mode="gui")`). Does not work with hython.

## License

MIT
