$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Push-Location $Root
try {
    Write-Host "[1/5] Installing desktop backend packaging dependency..."
    & $Python -m pip install -r backend\requirements-desktop.txt
    if ($LASTEXITCODE -ne 0) { throw "Failed to install desktop backend requirements." }

    Write-Host "[2/5] Building React frontend..."
    $env:VITE_API_BASE_URL = ""
    if (-not (Test-Path (Join-Path $Root "frontend\node_modules\.bin\tsc.cmd"))) {
        npm --prefix frontend ci
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
    }
    npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }

    Write-Host "[3/5] Installing Chromium into the desktop bundle..."
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Root "backend\build\ms-playwright"
    & $Python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "Playwright Chromium installation failed." }

    Write-Host "[4/5] Packaging FastAPI backend..."
    Push-Location (Join-Path $Root "backend")
    try {
        & $Python -m PyInstaller --noconfirm --clean --onedir --name agent-backend `
            --paths src --collect-all playwright --collect-all tiktoken desktop_entry.py
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller backend packaging failed." }
    }
    finally {
        Pop-Location
    }

    Write-Host "[5/5] Building Windows installer..."
    npm --prefix desktop install
    if ($LASTEXITCODE -ne 0) { throw "Desktop dependencies installation failed." }
    npm --prefix desktop run dist:win
    if ($LASTEXITCODE -ne 0) { throw "Electron Windows installer build failed." }

    Write-Host "`nInstaller created under desktop\release"
}
finally {
    Pop-Location
}
