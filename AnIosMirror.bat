@echo off
cd /d "%~dp0"
pythonw main.pyw
if errorlevel 1 (
    echo.
    echo An error occurred. Please check the output above.
    pause >nul
)
