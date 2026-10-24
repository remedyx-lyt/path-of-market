@echo off
rem Double-click to run M1-4 checks and live acceptance. Log: .runtime\m1-4-acceptance.log
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-m1-4-acceptance.ps1" %*
echo.
echo Done. Log file: .runtime\m1-4-acceptance.log
pause
