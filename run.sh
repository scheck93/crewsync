#!/usr/bin/env bash
# Loads .env (for TWILIO_AUTH_TOKEN) then runs crewsync.py with the given args.
# Example: ./run.sh clients/conor-backman/config.json
set -euo pipefail
cd "$(dirname "$0")"
set -a
[ -f .env ] && . ./.env
set +a
exec python3 crewsync.py "$@"
