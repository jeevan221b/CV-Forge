#!/usr/bin/env bash
# Start CV Forge in a detached tmux session unless it is already running.
# Idempotent; called by Mission Control's "Open Dashboard" (POST /api/launch/cv-forge).
export PATH="/data/data/com.termux/files/usr/bin:$PATH"
SESSION="cv-forge"
DIR="$(cd "$(dirname "$0")/.." && pwd)"

tmux has-session -t "$SESSION" 2>/dev/null && { echo "already running"; exit 0; }
mkdir -p "$DIR/logs"
# pipe-pane keeps a log after the session (and its scrollback) is gone.
tmux new-session -d -s "$SESSION" -c "$DIR" "exec ./scripts/nexus-serve.sh"
tmux pipe-pane -t "$SESSION" "cat >> '$DIR/logs/cv-forge.log'"
echo "started"
