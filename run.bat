@echo off
cd /d "%~dp0"
py collect.py
if errorlevel 1 (pause & exit /b 1)
start "" "%~dp0docs\index.html"
