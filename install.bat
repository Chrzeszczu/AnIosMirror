@echo off
title AnIosMirror Installer
cd /d "%~dp0"

echo ========================================
echo     AnIosMirror - One-Click Installer
echo ========================================
echo.

:: ---------- Check Python ----------
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please download Python 3.10+ from:
    echo   https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% found

:: ---------- Install dependencies ----------
echo.
echo [..] Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)
echo [OK] Dependencies installed

:: ---------- Create desktop shortcut ----------
echo.
echo [..] Creating desktop shortcut...
set "SHORTCUT=%USERPROFILE%\Desktop\AnIosMirror.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[Environment]::GetFolderPath('Desktop')+'\AnIosMirror.lnk'; $w=New-Object -ComObject WScript.Shell; $c=$w.CreateShortcut($s); $c.TargetPath='cmd.exe'; $c.Arguments='/c python main.py'; $c.WorkingDirectory='%~dp0'; $c.Description='AnIosMirror - Android / iOS Screen Mirroring'; $c.Save()"
if %errorlevel% neq 0 (
    echo [WARN] Could not create desktop shortcut (try running as Administrator)
    goto :done
)
echo [OK] Desktop shortcut created at %SHORTCUT%

:: ---------- Done ----------
:done
echo.
echo ========================================
echo   Installation complete!
echo ========================================
echo.
echo You can now launch AnIosMirror from the
echo desktop shortcut or by running:
echo   python main.py
echo.
pause
