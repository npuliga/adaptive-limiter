@echo off
REM adaptive-limiter :: status.bat

set SCRIPT_DIR=%~dp0
set APP_DIR=%SCRIPT_DIR%..\
set PID_FILE=%SCRIPT_DIR%app.pid

echo [*] adaptive-limiter :: status
echo.

python --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    for /f "delims=" %%v in ('python --version 2^>^&1') do echo   Python:  [OK] %%v
) else (
    echo   Python:  [X] Not found
)

cd /d "%APP_DIR%" && python -c "import sys; sys.path.insert(0,'.'); import src.limiter" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo   Library: [OK] src.limiter importable
) else (
    echo   Library: [X] src.limiter import failed
)

if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    echo   Process: [!] PID file exists (%PID%) - check Task Manager
) else (
    echo   Process: [!] No background process (library mode - normal)
)
