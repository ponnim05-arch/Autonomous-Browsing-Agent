@echo off
title Autonomous Browser Agent Launcher
echo ====================================================
echo   Starting Autonomous Fast Browser Agent (React UI)
echo ====================================================

echo Freeing port 8000 if in use...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /f /pid %%a >nul 2>&1

echo [1/2] Launching FastAPI Backend on http://127.0.0.1:8000...
start "FastAPI Backend" cmd /k "cd /d %~dp0backend && ..\.venv\Scripts\python -m uvicorn server:app --port 8000 --host 127.0.0.1 --loop asyncio"

timeout /t 2 /nobreak >nul

echo [2/2] Launching React + Vite Frontend on http://localhost:5173...
start "React Frontend" cmd /k "cd frontend && npm run dev"

timeout /t 2 /nobreak >nul

echo Opening browser at http://localhost:5173...
start http://localhost:5173

echo.
echo Application started! Keep the two console windows open while using the app.
pause
