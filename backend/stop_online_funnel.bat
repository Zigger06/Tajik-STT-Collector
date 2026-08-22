@echo off
cd /d "%~dp0"
tailscale funnel --https=443 off
echo Public Funnel stopped. Local data was not deleted.
pause
