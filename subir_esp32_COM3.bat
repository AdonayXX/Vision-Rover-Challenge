@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\subir_esp32.ps1" -Port COM3 %*

echo.
pause
