# Cash Desk — Learners Point finance ops

Next.js App Router UI for cash collectors and managers. Talks to the FastAPI backend at `/api/staff/*`.

## Local run

```powershell
cd cashdesk
copy .env.local.example .env.local
npm install
npm run dev -- -p 3001
```

Open http://localhost:3001 — sign in with the bootstrap manager from backend env:

- `STAFF_BOOTSTRAP_MANAGER_EMAIL`
- `STAFF_BOOTSTRAP_MANAGER_PASSWORD`
- `STAFF_JWT_SECRET` (required)

Also set `CASHDESK_ORIGIN=http://localhost:3001` on the backend for CORS.
