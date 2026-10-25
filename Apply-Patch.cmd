@echo off
cd /d "%~dp0"
py -3 --version >nul 2>&1
if errorlevel 1 (
  python patch_mapfan.py %*
) else (
  py -3 patch_mapfan.py %*
)
if errorlevel 1 pause
