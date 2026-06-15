@echo off
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo An error occurred. Please check the output above.
    pause >nul
)
