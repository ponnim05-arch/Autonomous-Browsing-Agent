@echo off
title AutoAgent - Autonomous Browser Agent
color 0A
cls

echo =====================================================================
echo           AutoAgent - Autonomous Browser Agent (NVIDIA AI)
echo =====================================================================
echo.
echo [1/3] Checking environment...

cd /d "%~dp0"

set PYTHON_EXE=
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    echo   - Found bundled virtual environment (.venv).
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        set "PYTHON_EXE=python"
        echo   - Using system Python.
    ) else (
        echo [ERROR] Python was not found. Please ensure .venv or Python is installed.
        pause
        exit /b 1
    )
)

echo [2/3] Preparing application...
echo   - AI Engine: NVIDIA AI Cloud (Default Key Built-in)
echo   - Access on Windows: http://localhost:8501
echo   - Access on Android: http://localhost:8501 (via same Wi-Fi or hosted URL)
echo.
echo [3/3] Launching AutoAgent...
start "" "http://localhost:8501"

"%PYTHON_EXE%" -m streamlit run ui/app.py --server.port=8501 --server.address=0.0.0.0

pause
