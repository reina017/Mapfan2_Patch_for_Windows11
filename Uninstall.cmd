@echo off
py -3 --version >nul 2>&1
if errorlevel 1 (
  python "%~dp0uninstall.py" --gui %*
) else (
  py -3 "%~dp0uninstall.py" --gui %*
)
if errorlevel 1 pause
