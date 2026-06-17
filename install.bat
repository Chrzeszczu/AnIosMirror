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

:: ---------- Download tools ----------
echo.
echo [..] Downloading required tools (ADB, scrcpy, UxPlay)...
python -c "import sys; sys.path.insert(0,'.'); from src.downloader import download_tools; ok=download_tools(print); sys.exit(0 if ok else 1)"
if %errorlevel% neq 0 (
    echo [WARN] Tool download had issues. The app will retry on first launch.
) else (
    python -c "import sys; sys.path.insert(0,'.'); from src.downloader import check_tools; missing=check_tools(); sys.exit(len(missing))"
    if %errorlevel% neq 0 (
        echo [WARN] Tools still missing after download. The app will retry on first launch.
    ) else (
        echo [OK] All tools downloaded
    )
)

:: ---------- Ask about desktop shortcut ----------
echo.
echo Do you want to create a desktop shortcut?
choice /c YN /m "Create shortcut"
if %errorlevel% equ 1 (
    echo.
    echo [..] Creating desktop shortcut...
    set "PS_FILE=%TEMP%\AnIosMirror_shortcut.ps1"
    set "VBS=%~dp0AnIosMirror.vbs"
    > "%PS_FILE%" (
        echo $s = [Environment]::GetFolderPath('Desktop') + '\AnIosMirror.lnk'
        echo $w = New-Object -ComObject WScript.Shell
        echo $c = $w.CreateShortcut($s)
        echo $c.TargetPath = 'wscript.exe'
        echo $c.Arguments = '"%VBS:"=""%"'
        echo $c.Description = 'AnIosMirror - Android / iOS Screen Mirroring'
        echo $c.Save()
    )
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_FILE%"
    set "EXITCODE=%errorlevel%"
    del "%PS_FILE%" 2>nul
    if %EXITCODE% neq 0 (
        echo [WARN] Could not create desktop shortcut (try running as Administrator)
    ) else (
        echo [OK] Desktop shortcut created
    )
) else (
    echo [..] Skipping desktop shortcut
)

:: ---------- Done ----------
:done
echo.
echo ========================================
echo   Installation complete!
echo ========================================
echo.
echo You can now launch AnIosMirror from the
echo desktop shortcut or by running:
echo   pythonw main.pyw
echo.
pause
