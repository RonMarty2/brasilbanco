@echo off
title Subir Cambios a GitHub - brasilbanco
cd /d "%~dp0"
echo ===================================================
echo SUBIENDO CAMBIOS A GITHUB
echo ===================================================
git add .
git commit -m "update: mejoras en sistema de remesas"
git push origin main
echo ===================================================
echo ACTUALIZACION COMPLETADA CON EXITO
echo ===================================================
pause
