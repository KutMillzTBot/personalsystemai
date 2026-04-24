@echo off
REM ================================================================
REM install.bat — One-click setup for MQ5 bridge server
REM Run with: install.bat (Windows)
REM ================================================================

echo Installing bridge server dependencies...
pip install -r requirements.txt

echo.
echo Done! Run your system with:
echo   python mq5_bridge_server.py
pause
