@echo off
title Unitree G1 SDK Simulator
echo ========================================================
echo   Iniciando Simulador Unitree G1 FastAPI en el puerto 8000
echo   HMI Web:      http://localhost:8000/
echo   Documentacion: http://localhost:8000/docs
echo   Docente:       http://localhost:8000/simulator
echo ========================================================
echo.
cd /d "%~dp0"
py -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
if %ERRORLEVEL% NEQ 0 (
    python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
)
pause
