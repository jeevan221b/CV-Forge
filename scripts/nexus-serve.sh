#!/usr/bin/env bash
# =============================================================================
#  CV Forge — in-tmux entrypoint on Nexus (Termux / Android)
# =============================================================================
#  Not meant to run 24/7: Mission Control starts it on demand through
#  scripts/nexus-start.sh, and the backend exits by itself after
#  CVFORGE_IDLE_SHUTDOWN_MINUTES without requests, which ends the tmux session.
#  The single FastAPI process serves both /api/* and the built frontend.
#
#  No termux-wake-lock here on purpose: Termux has one app-wide wake lock,
#  not a counter. Mission Control already holds it, and releasing it when
#  CV Forge stops would release it for every service on the phone.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

# Nexus defaults, used only when neither the environment nor backend/.env
# (written by nexus-setup.sh) sets them: the app loads .env without
# overriding the environment, so exporting unconditionally would mask it.
# Tailscale-only in practice like every other Nexus service; the access
# token covers the LAN side of 0.0.0.0.
default() {
  [ -n "${!1:-}" ] || grep -q "^$1=." backend/.env 2>/dev/null || export "$1=$2"
}
default CVFORGE_HOST 0.0.0.0
default CVFORGE_IDLE_SHUTDOWN_MINUTES 30

mkdir -p logs
echo "▶ cv-forge $(date -u +%FT%TZ)"
cd backend
exec .venv/bin/python -m app
