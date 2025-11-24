@echo off
REM Скрипт для запуска приложения с правильным виртуальным окружением
REM Использует venv из текущего проекта

cd /d "%~dp0"
call venv\Scripts\activate.bat
python main.py
pause

