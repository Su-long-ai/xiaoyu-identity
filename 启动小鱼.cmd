@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\cpod\deepseek-web-api\start-local.ps1" >nul 2>&1
start "" pyw -3.11 "%~dp0companion.py"
exit /b 0
