@echo off
cd /d "%~dp0"
py -3 --version >nul 2>&1
if errorlevel 1 (
  python install.py %*
) else (
  py -3 install.py %*
)
if errorlevel 1 pause
