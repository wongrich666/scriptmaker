@echo off
chcp 65001 >nul
echo === ScriptMaker Windows Development Environment ===

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found, please install Python first
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Error: Failed to create virtual environment
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Error: Failed to install dependencies
    pause
    exit /b 1
)

REM Set environment variables
set FLASK_ENV=development
set FLASK_DEBUG=true

echo Environment variables set:
echo FLASK_ENV=%FLASK_ENV%
echo FLASK_DEBUG=%FLASK_DEBUG%

REM Check if port is occupied
echo Checking port 60002...
netstat -an | findstr :60002 >nul
if not errorlevel 1 (
    echo Port 60002 is occupied, stopping processes...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :60002') do (
        taskkill /f /pid %%a >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
)

REM Start application
echo Starting application...
echo Application will run at http://localhost:60002
echo Press Ctrl+C to stop
echo.

python app.py

REM If application exits abnormally, pause to show error
if errorlevel 1 (
    echo.
    echo Application failed to start, please check error messages
    pause
) 