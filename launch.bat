@echo off
setlocal
cd /d "%~dp0"
python app.py
if errorlevel 1 (
  echo.
  echo Unable to start the MSF Costing Tool. Confirm Python 3.11 or newer is installed.
  pause
)
endlocal
