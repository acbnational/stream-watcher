@echo off
REM ──────────────────────────────────────────────────────────
REM  Install Stream Watcher as a Windows service.
REM  Run this script as Administrator.
REM ──────────────────────────────────────────────────────────────

echo.
echo  Stream Watcher — Service Installer
echo  ===================================
echo.

REM Check for admin
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  ERROR: This script must be run as Administrator.
    echo  Right-click and select "Run as administrator".
    pause
    exit /b 1
)

echo  Installing service...
python -m acb_sync.service install
if %ERRORLEVEL% neq 0 (
    echo  Failed to install service.
    pause
    exit /b 1
)

echo.
echo  Starting service...
python -m acb_sync.service start
if %ERRORLEVEL% neq 0 (
    echo  Service installed but failed to start.
    echo  Make sure the application is configured first by running:
    echo    python -m acb_sync
    pause
    exit /b 1
)

echo.
echo  Service installed and started successfully.
echo  The service will run in the background even when no user is logged in.
echo.
echo  To stop:   python -m acb_sync.service stop
echo  To remove: python -m acb_sync.service remove
echo.
pause
