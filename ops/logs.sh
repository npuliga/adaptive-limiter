#!/usr/bin/env bash
# adaptive-limiter :: logs.sh
# Tails the application log file.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/app.log"
LINES="${1:-50}"

echo -e "${CYAN}[*] adaptive-limiter :: logs${NC}"
echo ""

if [[ ! -f "$LOG_FILE" ]]; then
    echo -e "${YELLOW}[!] No log file found at: $LOG_FILE${NC}"
    echo "    Start a background demo with: ./start.sh --background"
    exit 0
fi

echo -e "Log file: $LOG_FILE"
echo -e "Showing last $LINES lines (Ctrl+C to exit):"
echo "--------------------------------------------"
tail -n "$LINES" -f "$LOG_FILE"
