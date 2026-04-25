@echo off
REM adaptive-limiter :: health-check.bat

set SCRIPT_DIR=%~dp0
set APP_DIR=%SCRIPT_DIR%..\
set FAILED=0

echo [*] adaptive-limiter :: health-check
echo.

python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   [X] Python not found
    set FAILED=1
) else (
    for /f "delims=" %%v in ('python --version 2^>^&1') do echo   [OK] %%v
)

if "%FAILED%"=="0" (
    cd /d "%APP_DIR%" && python -c "import sys; sys.path.insert(0,'.'); from src.limiter import AIMDController, ControllerConfig; from src.simulator import WorkloadSimulator; from src.metrics import MetricsCollector; print('imports ok')" 2>nul | find "imports ok" >nul
    if %ERRORLEVEL% equ 0 (
        echo   [OK] Core library imports (AIMDController, WorkloadSimulator, MetricsCollector)
    ) else (
        echo   [X] Core library import failed
        set FAILED=1
    )
)

echo.
if "%FAILED%"=="0" (
    echo [OK] Health check passed
    exit /b 0
) else (
    echo [X] Health check failed
    exit /b 1
)
