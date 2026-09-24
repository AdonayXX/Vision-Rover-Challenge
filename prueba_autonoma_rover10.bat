@echo off
setlocal
cd /d "%~dp0"
if not exist "vision-system\.venv\Scripts\python.exe" (
    echo Falta vision-system\.venv. Crea primero el entorno de vision.
    pause
    exit /b 1
)
"vision-system\.venv\Scripts\python.exe" -X utf8 -B -u "base-robots\robots\pc\prueba_transporte_cubo.py" --todos --robot-id 10 --usar-sensores %*
set "resultado=%errorlevel%"
echo.
pause
exit /b %resultado%
