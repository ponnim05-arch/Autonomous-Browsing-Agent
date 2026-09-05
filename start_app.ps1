# Autonomous Fast Browser Agent - Launch Script
# Launches both FastAPI Backend and React Frontend concurrently

Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  Starting Autonomous Fast Browser Agent (React UI) " -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Cyan

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Start FastAPI Backend in new window
Write-Host "`n[1/2] Starting FastAPI Backend on http://127.0.0.1:8000..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ROOT'; .\.venv\Scripts\python -m uvicorn server:app --port 8000 --host 127.0.0.1 --reload"

# 2. Wait 2 seconds for backend to initialize
Start-Sleep -Seconds 2

# 3. Start Vite React Frontend in new window
Write-Host "[2/2] Starting React + Vite Frontend on http://localhost:5173..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$ROOT\frontend'; npm run dev"

# 4. Open default browser
Start-Sleep -Seconds 2
Start-Process "http://localhost:5173"

Write-Host "`nApp successfully launched! Press any key to close this launcher." -ForegroundColor Green
