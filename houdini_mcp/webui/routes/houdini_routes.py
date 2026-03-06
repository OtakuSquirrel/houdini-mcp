"""Houdini installation and process discovery API routes."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

_SFX_ROOT = Path("C:/Program Files/Side Effects Software")
_PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent.parent / "houdini_plugin"
_STARTUP_SCRIPT = _PLUGIN_DIR / "houdini_mcp_startup.py"

# Must match the tag in lifecycle.py
_HOOK_TAG = "# [HoudiniMCP]"
_HOOK_LINE = (
    'exec(open(hou.homeHoudiniDirectory() + "/scripts/houdini_mcp_startup.py").read())'
    f'  {_HOOK_TAG}'
)


def _find_installations() -> list[dict]:
    """Discover installed Houdini versions."""
    results = []
    if not _SFX_ROOT.exists():
        return results
    for d in sorted(_SFX_ROOT.iterdir(), reverse=True):
        if d.name.startswith("Houdini ") and d.is_dir():
            version = d.name.replace("Houdini ", "")
            hython = d / "bin" / "hython.exe"
            gui_exe = d / "bin" / "houdinifx.exe"
            if not gui_exe.exists():
                gui_exe = d / "bin" / "houdini.exe"
            entry = {"version": version, "dir": str(d)}
            if gui_exe.exists():
                entry["gui_exe"] = str(gui_exe)
            if hython.exists():
                entry["hython"] = str(hython)
            if gui_exe.exists() or hython.exists():
                entry["startup_installed"] = _check_startup_installed(version)
                results.append(entry)
    return results


def _get_prefs_dir(version: str) -> Path:
    """Get Houdini prefs directory for a version."""
    match = re.match(r"(\d+\.\d+)", version)
    if not match:
        raise ValueError(f"Cannot parse version: {version}")
    major_minor = match.group(1)
    if os.name == "nt":
        return Path.home() / "Documents" / f"houdini{major_minor}"
    else:
        return Path.home() / f"houdini{major_minor}"


def _check_startup_installed(version: str) -> bool:
    """Check if our startup hook is installed for a version.

    Checks for the presence of houdini_mcp_startup.py AND our hook tag
    in 456.py.
    """
    try:
        prefs = _get_prefs_dir(version)
        scripts_dir = prefs / "scripts"
        startup_exists = (scripts_dir / "houdini_mcp_startup.py").exists()
        hook_file = scripts_dir / "456.py"
        hook_present = False
        if hook_file.exists():
            hook_present = _HOOK_TAG in hook_file.read_text(encoding="utf-8")
        return startup_exists and hook_present
    except Exception:
        return False


def _inject_hook(target_file: Path) -> str:
    """Append our hook line to a script file if not already present."""
    if target_file.exists():
        content = target_file.read_text(encoding="utf-8")
        if _HOOK_TAG in content:
            return "already_present"
        if not content.endswith("\n"):
            content += "\n"
        content += f"\n{_HOOK_LINE}\n"
        target_file.write_text(content, encoding="utf-8")
        return "injected"
    else:
        target_file.write_text(f"{_HOOK_LINE}\n", encoding="utf-8")
        return "created"


def _remove_hook(target_file: Path) -> str:
    """Remove our hook line from a script file."""
    if not target_file.exists():
        return "file_missing"
    content = target_file.read_text(encoding="utf-8")
    if _HOOK_TAG not in content:
        return "not_found"
    lines = [line for line in content.splitlines() if _HOOK_TAG not in line]
    while lines and lines[-1].strip() == "":
        lines.pop()
    target_file.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    return "removed"


@router.get("/versions")
async def list_versions():
    """List all detected Houdini installations with injection details."""
    installations = _find_installations()
    # Enrich with injection details
    for inst in installations:
        ver = inst["version"]
        try:
            prefs = _get_prefs_dir(ver)
            scripts_dir = prefs / "scripts"
            hook_file = scripts_dir / "456.py"
            startup_file = scripts_dir / "houdini_mcp_startup.py"
            inst["injection"] = {
                "prefs_dir": str(prefs),
                "scripts_dir": str(scripts_dir),
                "hook_file": str(hook_file),
                "hook_file_exists": hook_file.exists(),
                "startup_file": str(startup_file),
                "startup_file_exists": startup_file.exists(),
                "hook_line": _HOOK_LINE,
            }
        except Exception:
            inst["injection"] = None
    return {"installations": installations}


@router.get("/processes")
async def list_processes():
    """List running Houdini processes on the system."""
    processes = []
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq houdini*", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().split("\n"):
                if line and "houdini" in line.lower():
                    parts = line.strip('"').split('","')
                    if len(parts) >= 2:
                        processes.append({
                            "name": parts[0],
                            "pid": int(parts[1]) if parts[1].isdigit() else parts[1],
                            "mem": parts[4] if len(parts) > 4 else "",
                        })
            result2 = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq hython*", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result2.stdout.strip().split("\n"):
                if line and "hython" in line.lower():
                    parts = line.strip('"').split('","')
                    if len(parts) >= 2:
                        processes.append({
                            "name": parts[0],
                            "pid": int(parts[1]) if parts[1].isdigit() else parts[1],
                            "mem": parts[4] if len(parts) > 4 else "",
                        })
        except Exception as e:
            return {"error": str(e), "processes": []}

    return {"processes": processes}


@router.post("/startup/install")
async def install_startup(version: str | None = None):
    """Install MCP startup hook for a Houdini version.

    Non-destructive: copies houdini_mcp_startup.py as a separate file
    and injects a one-line hook into 456.py.
    """
    if not _STARTUP_SCRIPT.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Startup script not found: {_STARTUP_SCRIPT}",
        )

    installations = _find_installations()
    if not installations:
        raise HTTPException(status_code=404, detail="No Houdini installations found")

    targets = installations
    if version is not None:
        targets = [i for i in installations if i["version"].startswith(version)]
        if not targets:
            available = [i["version"] for i in installations]
            raise HTTPException(
                status_code=404,
                detail=f"Version '{version}' not found. Available: {available}",
            )

    results = {}
    for inst in targets:
        ver = inst["version"]
        prefs_dir = _get_prefs_dir(ver)
        scripts_dir = prefs_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copy startup script as separate file
        dest_script = scripts_dir / "houdini_mcp_startup.py"
        shutil.copy2(str(_STARTUP_SCRIPT), str(dest_script))

        # 2. Inject hook into 456.py only
        hook_file = scripts_dir / "456.py"
        hook_status = _inject_hook(hook_file)

        results[ver] = {
            "scripts_dir": str(scripts_dir),
            "startup_script": str(dest_script),
            "hook_status": hook_status,
        }

    return {"status": "installed", "versions": results}


@router.delete("/startup/uninstall")
async def uninstall_startup(version: str):
    """Remove MCP startup hook from a Houdini version.

    Removes the hook line from 456.py (preserving other content)
    and deletes houdini_mcp_startup.py.
    """
    try:
        prefs_dir = _get_prefs_dir(version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    scripts_dir = prefs_dir / "scripts"
    removed = []

    # 1. Remove hook from 456.py
    hook_file = scripts_dir / "456.py"
    hook_status = _remove_hook(hook_file)

    # 2. Delete our startup script
    startup_file = scripts_dir / "houdini_mcp_startup.py"
    if startup_file.exists():
        startup_file.unlink()
        removed.append(str(startup_file))

    return {
        "status": "uninstalled",
        "version": version,
        "hook_status": hook_status,
        "removed_files": removed,
    }
