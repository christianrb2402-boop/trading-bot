@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python main.py --live-paper-engine --run-minutes 60
