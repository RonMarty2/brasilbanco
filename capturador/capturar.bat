@echo off
cd /d "%~dp0"
if exist "capturador.exe" (capturador.exe) else (python capturador.py)
