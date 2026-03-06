@echo off
chcp 65001 >nul 2>&1
title Houdini MCP - Install

echo.
echo  ========================================
echo    Houdini MCP  -  Installation
echo  ========================================
echo.

:: ── Check Python ──
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python not found.
    echo.
    echo  Please install Python 3.11+ from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Show Python version
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo  Found: %PYVER%

:: Check version >= 3.11
for /f "tokens=2 delims= " %%a in ('python --version 2^>^&1') do set PYVER_NUM=%%a
for /f "tokens=1,2 delims=." %%a in ("%PYVER_NUM%") do (
    set PYMAJOR=%%a
    set PYMINOR=%%b
)
if %PYMAJOR% lss 3 (
    echo  [ERROR] Python 3.11+ required, found %PYVER_NUM%
    pause
    exit /b 1
)
if %PYMAJOR% equ 3 if %PYMINOR% lss 11 (
    echo  [ERROR] Python 3.11+ required, found %PYVER_NUM%
    pause
    exit /b 1
)

:: ── Create venv ──
if not exist ".venv" (
    echo.
    echo  Creating virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo  [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo  Done.
) else (
    echo  Virtual environment already exists.
)

:: ── Install dependencies ──
echo.
echo  Installing dependencies...
.venv\Scripts\pip.exe install -e ".[webui]" -q
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo  ========================================
echo    Installation complete!
echo  ========================================
echo.
echo  To start the WebUI:   start_webui.bat
echo  To start MCP server:  .venv\Scripts\houdini-mcp
echo.
pause
