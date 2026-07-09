# Railway deployment

This monorepo deploys as **two Railway services**.

## Service A — Backend API (webhook target)

| Setting | Value |
|---------|--------|
| Root Directory | `backend` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Dockerfile | `backend/Dockerfile` (optional) |

**Bitrix Outbound webhook Handler must be:**

```text
https://<your-backend-railway-domain>/webhooks/bitrix24
```

Do **not** point Bitrix at the frontend URL.

### Backend env vars (minimum)

- `DATABASE_URL`
- `PUBLIC_BASE_URL` = `https://<backend-domain>`
- `PAYMENT_FRONTEND_BASE_URL` = `https://<frontend-domain>`
- `FRONTEND_ORIGIN` = `https://<frontend-domain>`
- `BITRIX24_WEBHOOK_URL`, `BITRIX_WEBHOOK_SECRET`
- `BITRIX_FINANCE_GENERATE_LINK_STAGE_ID`, `BITRIX_FIELD_PAYMENT_LINK`, …
- Paymob keys (`PAYMOB_*`)
- `USE_MOCK_INTEGRATIONS=false` in production

After deploy, run migrations once (Railway one-off / release command):

```bash
alembic upgrade head
```

## Service B — Frontend (customer payment pages)

| Setting | Value |
|---------|--------|
| Root Directory | `frontend` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

### Frontend env vars

- `API_BASE_URL` = `https://<backend-domain>` (no trailing slash)

Payment links written to Bitrix look like:

```text
https://<frontend-domain>/payment/{token}
```

## Local two-process run

```powershell
# Terminal 1 — API
cd backend
$env:PYTHONPATH="."
..\..\..  # from repo root instead:

cd "C:\Users\LPA\Desktop\Finance Project LPA"
$env:PYTHONPATH="backend"
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001

# Terminal 2 — Frontend
$env:PYTHONPATH="frontend"
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir frontend --host 127.0.0.1 --port 3000
```

Or use `.\start.ps1` from the repo root (starts backend then frontend).
