@echo off
setlocal
cd /d "%~dp0"

call "%~dp0find_python.bat"
if errorlevel 1 (
  pause
  exit /b 1
)

%TAJIK_PYTHON_CMD% server.py export --output exports\dataset-latest
pause
