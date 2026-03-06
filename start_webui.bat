@echo off
start http://localhost:8765
.venv\Scripts\python.exe -m houdini_mcp.webui --reload
