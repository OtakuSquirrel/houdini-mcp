"""Configuration management for Houdini MCP.

Reads/writes ~/houdini_mcp/config.json with thread-safe access.
Auto-creates defaults if missing.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global config directory
MCP_HOME = Path.home() / "houdini_mcp"
CONFIG_FILE = MCP_HOME / "config.json"
SESSIONS_DIR = MCP_HOME / "sessions"

_DEFAULT_CONFIG = {
    "human_launch": {
        "auto_start_rpyc": False,
    },
    "agent_launch": {
        "auto_start_rpyc": True,
    },
    "port_range": [18811, 18899],
    "houdini_search_paths": ["C:/Program Files/Side Effects Software"],
}

_lock = threading.Lock()


def _ensure_dirs() -> None:
    """Create config and sessions directories if needed."""
    MCP_HOME.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    """Load config from disk, creating defaults if missing."""
    _ensure_dirs()
    with _lock:
        if not CONFIG_FILE.exists():
            _write_config_locked(_DEFAULT_CONFIG)
            return dict(_DEFAULT_CONFIG)
        try:
            text = CONFIG_FILE.read_text(encoding="utf-8")
            config = json.loads(text)
            # Merge with defaults for any missing keys
            merged = _deep_merge(_DEFAULT_CONFIG, config)
            return merged
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read config, using defaults: %s", e)
            return dict(_DEFAULT_CONFIG)


def save_config(config: dict[str, Any]) -> None:
    """Write config to disk."""
    _ensure_dirs()
    with _lock:
        _write_config_locked(config)


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge updates into existing config and save."""
    config = load_config()
    merged = _deep_merge(config, updates)
    save_config(merged)
    return merged


def get_houdini_search_paths() -> list[str]:
    """Return list of directories to scan for Houdini installations."""
    config = load_config()
    return config.get(
        "houdini_search_paths",
        _DEFAULT_CONFIG["houdini_search_paths"],
    )


def get_port_range() -> tuple[int, int]:
    """Return (min_port, max_port) from config."""
    config = load_config()
    port_range = config.get("port_range", _DEFAULT_CONFIG["port_range"])
    return (int(port_range[0]), int(port_range[1]))


def _write_config_locked(config: dict[str, Any]) -> None:
    """Write config file (caller must hold _lock)."""
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
