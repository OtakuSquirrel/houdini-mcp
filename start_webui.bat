@echo off
chcp 65001 >nul 2>&1
title Houdini MCP Manager - WebUI
echo.
echo  ========================================
echo    Houdini MCP Manager  -  WebUI Server
echo  ========================================
echo.
echo  Dashboard:  http://localhost:8765
echo  API Docs:   http://localhost:8765/docs
echo.
echo  This terminal runs the WebUI server.
echo  Do NOT close it while using the dashboard.
echo  Press Ctrl+C to stop the server.
echo.
echo  ----------------------------------------
echo.
start http://localhost:8765
.venv\Scripts\python.exe -m houdini_mcp.webui --reload
