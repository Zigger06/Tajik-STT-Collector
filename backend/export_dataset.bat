@echo off
cd /d "%~dp0"
py -3 server.py export --output exports\dataset-latest
pause
