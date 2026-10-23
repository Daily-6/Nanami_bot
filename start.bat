@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"
set "NANAMI_RUNTIME=%~dp0..\AstrBot"
if defined NANAMI_ASTRBOT_ROOT set "NANAMI_RUNTIME=%NANAMI_ASTRBOT_ROOT%"
if not exist "%NANAMI_RUNTIME%\.venv\Scripts\python.exe" (
    echo AstrBot is not installed. Run setup_astrbot.ps1 first.
    pause
    exit /b 1
)

echo Starting Nanami AstrBot. Dashboard: http://127.0.0.1:6185
"%NANAMI_RUNTIME%\.venv\Scripts\python.exe" "%~dp0scripts\run_astrbot.py"

rem Keep errors visible if AstrBot exits unexpectedly.
pause

