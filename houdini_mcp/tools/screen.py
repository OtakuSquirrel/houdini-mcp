"""Screen capture tools — capture Houdini windows and user desktop.

Uses Win32 API to find and capture specific Houdini windows,
including error dialogs, floating panels, and child windows.
"""

from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import subprocess
from ctypes import wintypes

from houdini_mcp.server import mcp

# Win32 constants
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _get_process_name(pid: int) -> str:
    """Get process executable name from PID via Win32 API."""
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(h)
    return ""


def _find_houdini_windows() -> list[dict]:
    """Enumerate all visible windows belonging to Houdini processes.

    Filters strictly by process executable name to avoid false positives
    from other apps whose window titles contain 'houdini' (e.g. VS Code
    editing HoudiniLearn files, Edge with Houdini MCP tab, File Explorer).
    """
    import win32gui
    import win32process

    # Known Houdini executable names (lowercase)
    _HOUDINI_EXES = {
        "houdinifx.exe", "houdini.exe", "houdinicore.exe",
        "hindie.exe", "happrentice.exe",
    }

    windows = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        pname = _get_process_name(pid)
        if pname in _HOUDINI_EXES:
            rect = win32gui.GetWindowRect(hwnd)
            x, y, x2, y2 = rect
            w = x2 - x
            h = y2 - y
            # Skip tiny windows (e.g. minimized launcher slivers < 50px)
            if w < 50 or h < 50:
                return True
            windows.append({
                "hwnd": hwnd,
                "title": title,
                "pid": pid,
                "process": pname,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
            })
        return True

    win32gui.EnumWindows(callback, None)
    return windows


def _capture_window(hwnd: int) -> "Image":
    """Capture a specific window by its handle using PrintWindow.

    Works even if the window is partially occluded.
    Falls back to region capture if PrintWindow fails.
    """
    import win32gui
    import win32ui
    import win32con
    from PIL import Image

    # Get window dimensions
    rect = win32gui.GetWindowRect(hwnd)
    x, y, x2, y2 = rect
    w = x2 - x
    h = y2 - y

    if w <= 0 or h <= 0:
        raise ValueError(f"Window has invalid size: {w}x{h}")

    try:
        # Try PrintWindow (captures even occluded windows)
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bitmap)

        # PW_RENDERFULLCONTENT = 2 (captures DWM composed content)
        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)

        img = Image.frombuffer(
            "RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr, "raw", "BGRX", 0, 1,
        )

        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)

        return img

    except Exception:
        # Fallback: region-based capture
        from PIL import ImageGrab
        return ImageGrab.grab(bbox=(x, y, x2, y2))


@mcp.tool()
def capture_houdini_windows(
    output_dir: str | None = None,
) -> list[dict]:
    """Capture screenshots of ALL Houdini windows (main window + floating panels + dialogs).

    EXPERIMENTAL: Requires Houdini running in GUI mode with a visible viewport.
    For headless rendering, use render_frame or render_preview instead.

    PREFERRED over capture_screen for all Houdini-related tasks.
    Always use this tool instead of capture_screen when you need to see
    Houdini's state — it only captures Houdini windows, avoiding other
    applications and protecting user privacy.

    It captures every window belonging to the Houdini process, including:
    - Main application window
    - Floating parameter editors
    - Error/warning dialog boxes
    - Render progress windows
    - Any other Houdini child windows

    Args:
        output_dir: Optional directory to save screenshots as PNG files.
                    If None, returns base64-encoded image data inline.

    Returns:
        List of dicts, one per captured window, each containing:
        - title: Window title
        - width/height: Dimensions
        - output_path (if output_dir set) OR image_base64 (inline)
    """
    windows = _find_houdini_windows()

    if not windows:
        return [{"error": "No Houdini windows found. Houdini may not be running."}]

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    results = []
    for i, win in enumerate(windows):
        try:
            img = _capture_window(win["hwnd"])
            w, h = img.size

            info = {
                "title": win["title"],
                "process": win["process"],
                "width": w,
                "height": h,
                "window_index": i,
            }

            if output_dir:
                safe_title = "".join(
                    c if c.isalnum() or c in "-_ " else "_"
                    for c in win["title"]
                )[:60]
                filename = f"houdini_window_{i}_{safe_title}.png"
                path = os.path.join(output_dir, filename)
                img.save(path, "PNG")
                info["output_path"] = path
            else:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                info["image_base64"] = base64.b64encode(buf.getvalue()).decode("ascii")

            results.append(info)

        except Exception as e:
            results.append({
                "title": win["title"],
                "error": str(e),
                "window_index": i,
            })

    return results


@mcp.tool()
def capture_screen(
    output_path: str | None = None,
    region: str | None = None,
) -> dict:
    """Capture a screenshot of the entire desktop or a specific region.

    WARNING: This captures the ENTIRE screen, which may include other
    applications and sensitive user information. Only use this when you
    specifically need to see the full desktop or a non-Houdini region.

    For Houdini-related tasks, ALWAYS use capture_houdini_windows instead —
    it captures only Houdini windows and protects user privacy.

    Use this tool ONLY for:
    - Capturing the full desktop to see all applications
    - Capturing a specific screen region by coordinates

    Args:
        output_path: Optional file path to save the screenshot.
                     If None, returns base64-encoded image data.
        region: Optional region as 'x,y,width,height' (e.g. '0,0,1920,1080').
                If None, captures the entire primary screen.

    Returns:
        Dict with screenshot info.
    """
    from PIL import ImageGrab

    if region:
        parts = [int(x.strip()) for x in region.split(",")]
        if len(parts) != 4:
            raise ValueError("region must be 'x,y,width,height'")
        x, y, w, h = parts
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    else:
        img = ImageGrab.grab()

    width, height = img.size

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        img.save(output_path, "PNG")
        return {"output_path": output_path, "width": width, "height": height}
    else:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {"width": width, "height": height, "image_base64": b64, "format": "png"}


@mcp.tool()
def get_houdini_windows() -> list[dict]:
    """List all Houdini windows with their positions and sizes.

    Use this to see how many Houdini windows are open before capturing.

    Returns:
        List of dicts with title, process name, position, and size.
    """
    windows = _find_houdini_windows()
    # Remove hwnd (not serializable) from output
    return [
        {k: v for k, v in w.items() if k != "hwnd"}
        for w in windows
    ]


@mcp.tool()
def check_process_status(process_name: str = "houdini") -> dict:
    """Check if a specific process is running and get its status.

    Use this to detect if Houdini has crashed, is hung, or is showing
    error dialogs.

    Args:
        process_name: Name of the process to check (e.g. 'houdini', 'houdinifx').

    Returns:
        Dict with process status, memory usage, and responding state.
    """
    result = {
        "process_name": process_name,
        "running": False,
        "instances": [],
    }

    try:
        ps_script = (
            f"Get-Process -Name '*{process_name}*' -ErrorAction SilentlyContinue | "
            "Select-Object ProcessName, Id, CPU, "
            "@{N='MemoryMB';E={[math]::Round($_.WorkingSet64/1MB,1)}}, "
            "Responding, MainWindowTitle | ConvertTo-Json"
        )
        ps_result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if ps_result.returncode == 0 and ps_result.stdout.strip():
            data = json.loads(ps_result.stdout)
            if isinstance(data, dict):
                data = [data]
            for proc in data:
                result["instances"].append({
                    "name": proc.get("ProcessName", ""),
                    "pid": proc.get("Id", 0),
                    "memory_mb": proc.get("MemoryMB", 0),
                    "responding": proc.get("Responding", False),
                    "window_title": proc.get("MainWindowTitle", ""),
                })
            result["running"] = len(result["instances"]) > 0
    except Exception as e:
        result["error"] = str(e)

    return result
