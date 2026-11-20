@echo off
chcp 65001 >nul
"D:\xiaoyu_external_audit\N.E.K.O\.venv\Scripts\python.exe" "%~dp0api_cost_report.py" --open
if errorlevel 1 pause
