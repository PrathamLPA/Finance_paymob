# Start Finance Automation locally (API on 8001 + Frontend on 3000)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example" -ForegroundColor Yellow
}

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    .venv\Scripts\pip install -r backend\requirements.txt
    .venv\Scripts\pip install -r frontend\requirements.txt
}

Write-Host "Running database migrations..." -ForegroundColor Cyan
Push-Location backend
$env:PYTHONPATH = (Get-Location).Path
& "$PSScriptRoot\.venv\Scripts\python.exe" -m alembic upgrade head
Pop-Location

Write-Host ""
Write-Host "Backend (API):     http://localhost:8001" -ForegroundColor Green
Write-Host "Frontend (pages):  http://localhost:3000" -ForegroundColor Green
Write-Host "Bitrix Handler:    https://<API_PUBLIC>/webhooks/bitrix24" -ForegroundColor Yellow
Write-Host ""
Write-Host "Starting both services. Ctrl+C stops the frontend; stop the backend window separately if needed." -ForegroundColor Cyan

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$PSScriptRoot\backend'; `$env:PYTHONPATH='.'; & '$PSScriptRoot\.venv\Scripts\python.exe' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001"
)

Start-Sleep -Seconds 2
Set-Location "$PSScriptRoot\frontend"
$env:PYTHONPATH = (Get-Location).Path
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 3000
