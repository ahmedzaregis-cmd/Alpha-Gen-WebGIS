@echo off
chcp 65001 >nul
title Alpha GIS Platform
echo ============================================
echo   Alpha GIS Platform  -  rodat gil alpha
echo   http://localhost:8765
echo ============================================
cd /d "%~dp0"
python -m uvicorn server.main:app --host 127.0.0.1 --port 8765 --log-level warning
pause
