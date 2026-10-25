@echo off
py -3 --version >nul 2>&1
if errorlevel 1 (
  python "%~dp0uninstall.py" --gui --register-only %*
) else (
  py -3 "%~dp0uninstall.py" --gui --register-only %*
)
if errorlevel 1 pause
