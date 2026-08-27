#!/bin/sh
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$APP_DIR/.." && pwd)"
STATIC="$APP_DIR/app/cashdesk_static"
cd "$APP_DIR"
if [ ! -f "$STATIC/login/index.html" ] && [ -f "$ROOT/cashdesk/package.json" ]; then
  echo "[start] Building Cash Desk static export..."
  (cd "$ROOT/cashdesk" && npm ci && npm run build)
  rm -rf "$STATIC"
  mkdir -p "$STATIC"
  cp -r "$ROOT/cashdesk/out/." "$STATIC/"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-3000}"
