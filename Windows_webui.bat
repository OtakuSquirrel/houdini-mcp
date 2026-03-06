@echo off
chcp 65001 >nul 2>&1
title Houdini MCP Manager - WebUI

:: ── Check venv ──
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  [ERROR] Virtual environment not found.
    echo  Please run install.bat first.
    echo.
    pause
    exit /b 1
)

echo.
echo  ========================================
echo    Houdini MCP Manager  -  WebUI Server
echo  ========================================
echo.
echo  Dashboard:  http://localhost:9800
echo  API Docs:   http://localhost:9800/docs
echo.
echo  This terminal runs the WebUI server.
echo  Do NOT close it while using the dashboard.
echo  Press Ctrl+C to stop the server.
echo.
echo  ----------------------------------------
echo.
start http://localhost:9800
.venv\Scripts\python.exe -m houdini_mcp.webui --port 9800 --reload
