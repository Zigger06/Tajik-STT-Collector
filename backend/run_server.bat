@echo off
setlocal
cd /d "%~dp0"

call "%~dp0find_python.bat"
if errorlevel 1 (
  pause
  exit /b 1
)

set "TAJIK_COLLECTOR_API_KEY=tajik-stt-local"
%TAJIK_PYTHON_CMD% server.py serve --host 0.0.0.0 --port 8000
pause
