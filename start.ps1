# Start Finance Automation locally (PostgreSQL + API server)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Starting PostgreSQL..." -ForegroundColor Cyan
docker compose up -d
Start-Sleep -Seconds 4

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example" -ForegroundColor Yellow
}

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
}

$env:PYTHONPATH = "."
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue

Write-Host "Running database migrations..." -ForegroundColor Cyan
.venv\Scripts\python.exe -m alembic upgrade head

Write-Host ""
Write-Host "Starting server at http://localhost:8000" -ForegroundColor Green
Write-Host "  API docs:    http://localhost:8000/docs" -ForegroundColor Green
Write-Host "  Health:      http://localhost:8000/health" -ForegroundColor Green
Write-Host ""
Write-Host "To create a test payment page, run in another terminal:" -ForegroundColor Yellow
Write-Host '  Invoke-RestMethod -Uri "http://localhost:8000/api/dev/send-payment-link" -Method POST -ContentType "application/json" -Body ''{"lead_id": 1001, "customer_email": "you@example.com", "total_amount": "10000"}''' -ForegroundColor Gray
Write-Host ""

.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
