#!/usr/bin/env bash
# adaptive-limiter :: stop.sh
# Stops any background demo process.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/app.pid"

echo -e "${CYAN}[*] adaptive-limiter :: stop${NC}"

if [[ ! -f "$PID_FILE" ]]; then
    echo -e "${YELLOW}[!] No PID file found - nothing to stop.${NC}"
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    rm -f "$PID_FILE"
    echo -e "${GREEN}[OK] Process $PID stopped.${NC}"
else
    echo -e "${YELLOW}[!] Process $PID not found. Cleaning up PID file.${NC}"
    rm -f "$PID_FILE"
fi
