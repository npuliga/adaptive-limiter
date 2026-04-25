@echo off
REM adaptive-limiter :: restart.bat

set SCRIPT_DIR=%~dp0
echo [*] adaptive-limiter :: restart
call "%SCRIPT_DIR%stop.bat"
call "%SCRIPT_DIR%start.bat"
