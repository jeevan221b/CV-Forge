#!/usr/bin/env bash
# =============================================================================
#  CV Forge — install / update on Nexus. Run on Nexus from the repo root:
#      ./scripts/nexus-setup.sh
#  Idempotent: (re)creates the venv deps, builds the frontend, and writes
#  backend/.env with a fresh access token only if there isn't one yet.
#  Does not start the app; Mission Control does that on demand.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${CVFORGE_PORT:-8000}"
# pydantic-core has no wheel for Termux, so pip builds it with Rust (pkg install rust;
# slow on a phone, and only the first time). maturin needs the API level to target.
if command -v getprop >/dev/null 2>&1; then
  export ANDROID_API_LEVEL="${ANDROID_API_LEVEL:-$(getprop ro.build.version.sdk)}"
fi

echo "==> python deps"
( cd backend
  [ -d .venv ] || python -m venv .venv
  .venv/bin/pip install -q --disable-pip-version-check -r requirements.txt
  .venv/bin/python -c "import fastapi, pydantic, pypdf; print('deps ok')" )

echo "==> frontend build"
# `vite build` rather than `npm run build`: the latter type-checks first, and TypeScript 7's native
# compiler ships no Android binary. Type-check on the laptop (npm run typecheck) instead.
( cd frontend && (npm ci --no-audit --no-fund -s || npm install --no-audit --no-fund -s) && npx vite build )

if [ ! -f backend/.env ]; then
  echo "==> writing backend/.env (new access token)"
  cat > backend/.env <<ENV
# Nexus settings. Mission Control reads CVFORGE_ACCESS_TOKEN and CVFORGE_PORT from here.
GROQ_API_KEY=
CVFORGE_HOST=0.0.0.0
CVFORGE_PORT=$PORT
CVFORGE_ACCESS_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
CVFORGE_IDLE_SHUTDOWN_MINUTES=30
# Same-origin only: the backend serves the built UI itself.
CVFORGE_ALLOWED_ORIGINS=
ENV
  chmod 600 backend/.env
fi
chmod +x scripts/*.sh
echo "==> done. Start: ./scripts/nexus-start.sh   Stop: ./scripts/nexus-stop.sh"
