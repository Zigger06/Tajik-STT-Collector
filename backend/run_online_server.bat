@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3 is not installed or the py launcher is unavailable.
  echo Install Python 3, then run this file again.
  pause
  exit /b 1
)

where tailscale >nul 2>nul
if errorlevel 1 (
  echo Tailscale is not installed or is not in PATH.
  echo Install Tailscale for Windows and sign in first.
  echo https://tailscale.com/download/windows
  pause
  exit /b 1
)

echo Creating a public HTTPS address for the Android API...
echo The first run may open a browser to approve Tailscale Funnel.
tailscale funnel --bg --https=443 http://127.0.0.1:8000
if errorlevel 1 (
  echo Could not enable Tailscale Funnel. Read the message above.
  pause
  exit /b 1
)

echo.
echo Copy the https://...ts.net address below. This is the Android server URL.
tailscale funnel status
echo.
echo The admin panel will be available ONLY on this PC:
echo http://127.0.0.1:8001/admin
echo.
py -3 server.py online --public-host 127.0.0.1 --public-port 8000 --admin-host 127.0.0.1 --admin-port 8001
pause
