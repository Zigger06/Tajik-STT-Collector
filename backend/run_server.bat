@echo off
cd /d "%~dp0"
set "TAJIK_COLLECTOR_API_KEY=tajik-stt-local"
py -3 server.py serve --host 0.0.0.0 --port 8000
pause
