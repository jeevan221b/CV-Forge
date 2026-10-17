#!/usr/bin/env bash
# Stop CV Forge on Nexus. Called by Mission Control's "Shut down" button.
export PATH="/data/data/com.termux/files/usr/bin:$PATH"
tmux kill-session -t cv-forge 2>/dev/null && echo stopped || echo "was not running"
