# Railway deployment

This monorepo deploys as **two Railway services**.

## Service A — Backend API (webhook target)

| Setting | Value |
|---------|--------|
| Root Directory | `backend` |
| Start command | `sh start.sh` (reads Railway `PORT` env) |
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

Migrations run automatically on every deploy via `backend/start.sh` (`alembic upgrade head` before uvicorn).

Verify production:

```text
GET https://<backend>/          → API info JSON (not a web page)
GET https://<backend>/health    → {"status":"ok"}
GET https://<backend>/ready     → database check (must show database: ok)
GET https://<frontend>/health   → finance-payment-frontend
```

**Common mistake:** Opening backend root `/` shows API JSON — payment UI is only at `https://<frontend>/payment/{token}`.

Copy **all** variables from [`backend/railway.env.example`](backend/railway.env.example) into Railway backend (not just the 4 URL vars). Missing `DATABASE_URL` causes 500 on payment link creation.

## Service B — Frontend (customer payment pages + Cash Desk at `/cashdesk`)

| Setting | Value |
|---------|--------|
| **Root Directory** | `.` (repository root — **not** `frontend`) |
| **Dockerfile Path** | `Dockerfile.frontend` |
| Start command | (from Dockerfile) `sh start.sh` |

Cash Desk is a static Next.js export served under `/cashdesk/*` on the **same host** as payment links. `/payment/{token}` and `/approvals/{token}` are unchanged.

### Frontend env vars

- `API_BASE_URL` = `https://<backend-domain>` (no trailing slash)
- `NEXT_PUBLIC_API_BASE_URL` = same as `API_BASE_URL` (**required at Docker build** for Cash Desk API calls)

Payment links written to Bitrix look like:

```text
https://<frontend-domain>/payment/{token}
```

Cash Desk login (after deploy):

```text
https://<frontend-domain>/cashdesk/login/
```

Backend `CASHDESK_ORIGIN` should be the **frontend domain** (same URL as `FRONTEND_ORIGIN`).

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
