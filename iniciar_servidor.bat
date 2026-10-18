@echo off
title Sistema de Control de Remesas Brasil-Bolivia
cd /d "%~dp0backend"
echo ===================================================
echo INICIANDO SERVIDOR DE CONTROL DE REMESAS
echo ===================================================
echo Backend API:  http://localhost:8000
echo App PWA:      http://localhost:8000/pwa
echo ===================================================
start http://localhost:8000/pwa
.\venv\Scripts\python main.py
pause
