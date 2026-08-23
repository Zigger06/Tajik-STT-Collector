@echo off
set "TAJIK_PYTHON_CMD="

where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" >nul 2>nul
  if not errorlevel 1 set "TAJIK_PYTHON_CMD=py -3"
)
if defined TAJIK_PYTHON_CMD exit /b 0

where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" >nul 2>nul
  if not errorlevel 1 set "TAJIK_PYTHON_CMD=python"
)
if defined TAJIK_PYTHON_CMD exit /b 0

where python3 >nul 2>nul
if not errorlevel 1 (
  python3 -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" >nul 2>nul
  if not errorlevel 1 set "TAJIK_PYTHON_CMD=python3"
)
if defined TAJIK_PYTHON_CMD exit /b 0

echo Python 3 could not be found.
echo Checked the py -3, python, and python3 commands.
echo Reinstall Python with Add Python to PATH enabled, then try again.
exit /b 1
