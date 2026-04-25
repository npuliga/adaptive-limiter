@echo off
REM adaptive-limiter :: stop.bat

set SCRIPT_DIR=%~dp0
set PID_FILE=%SCRIPT_DIR%app.pid

echo [*] adaptive-limiter :: stop

if not exist "%PID_FILE%" (
    echo [!] No PID file found - nothing to stop.
    exit /b 0
)

set /p PID=<"%PID_FILE%"
taskkill /PID %PID% /F >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Process %PID% stopped.
) else (
    echo [!] Process %PID% not found. Cleaning up PID file.
)
del /f "%PID_FILE%" >nul 2>&1
