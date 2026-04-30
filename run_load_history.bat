@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python main.py --load-history --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT --timeframe 1m --limit 1000
