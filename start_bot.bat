@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Сначала создай venv и установи зависимости: pip install -r requirements.txt
  pause
  exit /b 1
)
"venv\Scripts\python.exe" bot.py
pause
