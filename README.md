# houdini-mcp

MCP (Model Context Protocol) server for SideFX Houdini. Enables AI assistants
(Claude Code, etc.) to control Houdini via RPyC — creating nodes, setting parameters,
running Python in Houdini's context, capturing viewport screenshots, and more.

## Architecture

```
Claude Code / AI Assistant
         |
    MCP (stdio)
         |
  houdini-mcp server
  (Python 3.11+, external process)
         |
   RPyC port 18811
         |
   Houdini (hrpyc, embedded Python 3.10/3.11)
```

The MCP server runs as a separate process from Houdini. They communicate via
RPyC over TCP (localhost:18811). The server process uses Python 3.11+; Houdini's
embedded Python version (3.10 for H20.5, 3.11 for H21.0) is independent.

## Requirements

- Python 3.11+ (external environment — conda or venv)
- SideFX Houdini 20.5 or 21.0
- Windows (screen capture tools use Win32 API; all other tools are cross-platform)

## Installation

```bash
# Clone the repository
git clone https://github.com/<your-org>/houdini-mcp.git
cd houdini-mcp

# Install in a Python 3.11+ environment
pip install -e .

# Install dev dependencies (optional, for running tests)
pip install -e ".[dev]"
```

## Claude Code Configuration

Add to `.claude/settings.local.json` in your project (or copy the one in this repo):

```json
{
  "mcpServers": {
    "houdini": {
      "command": "/path/to/python3.11",
      "args": ["-m", "houdini_mcp"],
      "cwd": "/path/to/houdini-mcp"
    }
  }
}
```

Replace `/path/to/python3.11` with your Python 3.11+ interpreter and
`/path/to/houdini-mcp` with the directory containing this README.

The MCP server communicates via **stdio** transport (FastMCP default) — no HTTP
server or port needed for the MCP connection itself. Only the RPyC link to
Houdini uses a TCP port (18811).

## Quick Start

### 1. Install Houdini startup scripts

One-time setup. Call the `install_startup_scripts` MCP tool, which deploys
`houdini_plugin/houdini_mcp_startup.py` to the correct Houdini prefs
directory (auto-detected for each installed version):

```
install_startup_scripts()
# Installs to ~/Documents/houdini21.0/scripts/{pythonrc,123,456}.py
# and ~/Documents/houdini20.5/scripts/{pythonrc,123,456}.py (if installed)
```

Or call `start_houdini(mode="gui")` — it auto-installs if scripts are missing.

Startup log is written to `~/houdini_mcp/houdini_startup.log`.

### 2. Use the tools

Recommended entry point:

```
ensure_houdini_ready()   → starts Houdini if not running, connects via RPyC
get_scene_summary()      → overview of the current scene
create_node("/obj", "geo", "mysphere")
set_parameter("/obj/mysphere/sphere1", "rad", 2.0)
get_geometry_info("/obj/mysphere/sphere1")
viewport_screenshot("/tmp/view.png")
```

## Available Tools (37 total)

| Category | Tools |
|---|---|
| **Lifecycle** | `get_houdini_status`, `start_houdini`, `stop_houdini`, `ensure_houdini_ready`, `install_startup_scripts` |
| **Scene** | `new_scene`, `save_hip`, `open_hip`, `get_scene_summary` |
| **Nodes** | `create_node`, `delete_node`, `get_node_info`, `get_node_tree`, `get_node_children` |
| **Parameters** | `get_parameter`, `set_parameter`, `get_parm_template` |
| **Connections** | `connect_nodes`, `disconnect_nodes`, `get_connections` |
| **Execution** | `execute_python`, `cook_node`, `get_node_errors` |
| **Geometry** | `get_geometry_info`, `get_point_positions`, `get_attribute_values` |
| **Viewport** | `viewport_screenshot`, `set_viewport` |
| **Render** | `render_frame`, `render_preview` |
| **Learning** | `compare_screenshots`, `export_node_network`, `get_scene_diff` |
| **Screen** | `capture_houdini_windows`, `get_houdini_windows`, `capture_screen`, `check_process_status` |

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
script (`houdini_plugin/houdini_mcp_startup.py`) — deployed to
`~/Documents/houdiniX.Y/scripts/` via `install_startup_scripts` — runs when Houdini starts
and calls `hrpyc.start_server(port=18811)`. The MCP server connects with
`rpyc.classic.connect("localhost", 18811)` and accesses the full `hou` module
remotely via `conn.modules.hou`.

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
- Ensure startup scripts are installed: call `install_startup_scripts()`
- Restart Houdini after installing scripts
- Check `~/houdini_mcp/houdini_startup.log` for errors

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
