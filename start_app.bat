@echo off
title Autonomous Browser Agent Launcher
echo ====================================================
echo   Starting Autonomous Fast Browser Agent (React UI)
echo ====================================================

echo [1/2] Launching FastAPI Backend on http://127.0.0.1:8000...
start "FastAPI Backend" cmd /k ".\.venv\Scripts\python -m uvicorn server:app --port 8000 --host 127.0.0.1 --reload"

timeout /t 2 /nobreak >nul

echo [2/2] Launching React + Vite Frontend on http://localhost:5173...
start "React Frontend" cmd /k "cd frontend && npm run dev"

timeout /t 2 /nobreak >nul

echo Opening browser at http://localhost:5173...
start http://localhost:5173

echo.
echo Application started! Keep the two console windows open while using the app.
pause
