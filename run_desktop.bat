@echo off
cd /d "%~dp0"
python "%~dp0desktop\app.py" %*
if errorlevel 1 (
    echo.
    echo Application exited with an error.
    pause
)
