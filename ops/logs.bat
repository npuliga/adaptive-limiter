@echo off
REM adaptive-limiter :: logs.bat

set SCRIPT_DIR=%~dp0
set LOG_FILE=%SCRIPT_DIR%app.log

echo [*] adaptive-limiter :: logs
echo.

if not exist "%LOG_FILE%" (
    echo [!] No log file found at: %LOG_FILE%
    echo     Start a background demo with: start.bat
    exit /b 0
)

echo Log file: %LOG_FILE%
powershell -Command "Get-Content '%LOG_FILE%' -Wait -Tail 50"
