@echo off
title AnIosMirror Updater
cd /d "%~dp0"

echo ========================================
echo      AnIosMirror - Updater
echo ========================================
echo.

:: ---------- Pull latest code ----------
echo [..] Pulling latest code from GitHub...
git pull
if %errorlevel% neq 0 (
    echo [WARN] git pull failed. Skipping code update.
    echo        Make sure git is installed and the repo was cloned, not downloaded as ZIP.
)

:: ---------- Update Python dependencies ----------
echo.
echo [..] Updating Python dependencies...
pip install --upgrade -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] pip upgrade failed.
    pause
    exit /b 1
)
echo [OK] Dependencies updated

:: ---------- Re-download tools ----------
echo.
echo [..] Checking tools...
python -c "import sys; sys.path.insert(0,'.'); from src.downloader import check_tools; sys.exit(len(check_tools()))"
if %errorlevel% equ 0 (
    echo [OK] Tools already up to date
    goto :done
)
echo Some tools are missing.
echo Would you like to re-download all tools?
choice /c YN /m "Re-download tools"
if %errorlevel% equ 1 (
    echo [..] Re-downloading tools...
    python -c "import sys; sys.path.insert(0,'.'); from src.downloader import clean_tools, download_tools; clean_tools(); download_tools(print)"
    if %errorlevel% neq 0 (
        echo [ERROR] Tool download failed.
        pause
        exit /b 1
    )
    echo [OK] Tools updated
) else (
    echo [..] Skipping tool re-download
)

:: ---------- Done ----------
:done
echo.
echo ========================================
echo     Update complete!
echo ========================================
echo.
pause
