@echo off
setlocal
cd /d "%~dp0"
echo SARBA GUI Windows Build
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\build_windows.ps1"
if errorlevel 1 (
  echo.
  echo Build did not complete. Read the error above.
  pause
  exit /b 1
)
echo.
echo Build finished. Check the dist folder.
pause
