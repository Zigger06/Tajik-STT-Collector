@echo off
setlocal
cd /d "%~dp0"

call "%~dp0find_python.bat"
if errorlevel 1 (
  pause
  exit /b 1
)

if "%~1"=="" (
  echo Drag a TXT or CSV file onto import_texts.bat
  pause
  exit /b 1
)

%TAJIK_PYTHON_CMD% server.py import-texts "%~1" --source manual --voices 5
pause
