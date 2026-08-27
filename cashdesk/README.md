# Cash Desk — Learners Point finance ops

Next.js UI for cash collectors and managers. In production it is served from the **payment frontend** at `/cashdesk/*` (same host as `/payment/{token}`).

## Local run (standalone dev server)

```powershell
cd cashdesk
copy .env.local.example .env.local
npm install
npm run dev -- -p 3001
```

Open http://localhost:3001/cashdesk/login/ (basePath is `/cashdesk`).

## Local run (via payment frontend — matches production)

From repo root, with backend on 8001:

```powershell
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8001"
cd frontend
sh start.sh   # builds cashdesk export if missing, then uvicorn
```

Open http://localhost:3000/cashdesk/login/

Sign in with bootstrap manager from backend `.env` (`STAFF_BOOTSTRAP_MANAGER_*`, `STAFF_JWT_SECRET`).
