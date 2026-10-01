@echo off
title AtmosGuard Server
echo ========================================================
echo               Starting AtmosGuard System
echo ========================================================
echo.

if exist "%~dp0backend" (
    cd /d "%~dp0backend"
) else (
    echo Error: Cannot find backend directory.
    pause
    exit /b 1
)

echo Starting server on http://127.0.0.1:8000 ...
echo Press Ctrl+C in this window to stop the server.
echo.
start http://127.0.0.1:8000
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
pause
