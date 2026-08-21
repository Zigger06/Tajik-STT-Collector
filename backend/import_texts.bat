@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag a TXT or CSV file onto import_texts.bat
  pause
  exit /b 1
)
py -3 server.py import-texts "%~1" --source manual --voices 5
pause
