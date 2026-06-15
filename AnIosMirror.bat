@echo off
cd /d "%~dp0"
"C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe" main.py
if errorlevel 1 (
    echo.
    echo Wystapil blad. Kliknij dowolny klawisz aby zamknac.
    pause >nul
)
