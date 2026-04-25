@echo off
REM adaptive-limiter :: start.bat
REM Starts a demo run of the adaptive limiter library.

set SCRIPT_DIR=%~dp0
set APP_DIR=%SCRIPT_DIR%..\
set PID_FILE=%SCRIPT_DIR%app.pid
set LOG_FILE=%SCRIPT_DIR%app.log

echo [*] adaptive-limiter
echo.
echo [!] This is a Python library / demo CLI - it does not run as a persistent server.
echo.
echo To run the demo simulation:
echo   cd /d %APP_DIR%
echo   python -m src.main
echo   python -m src.main --scenario traffic_spike
echo   python -m src.main --list-scenarios
echo.
echo To use as a library:
echo   from src.limiter import AIMDController, ControllerConfig
echo.
