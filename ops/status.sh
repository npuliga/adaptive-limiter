#!/usr/bin/env bash
# adaptive-limiter :: status.sh
# Shows status of any background demo process.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$SCRIPT_DIR/app.pid"

echo -e "${CYAN}[*] adaptive-limiter :: status${NC}"
echo ""

# Python availability
if command -v python3 &>/dev/null; then
    echo -e "  Python:  ${GREEN}[OK]${NC} $(python3 --version)"
elif command -v python &>/dev/null; then
    echo -e "  Python:  ${GREEN}[OK]${NC} $(python --version)"
else
    echo -e "  Python:  ${RED}[X] Not found${NC}"
fi

# Library import check
PYTHON=$(command -v python3 || command -v python)
if "$PYTHON" -c "import sys; sys.path.insert(0,'$APP_DIR'); import src.limiter" 2>/dev/null; then
    echo -e "  Library: ${GREEN}[OK]${NC} src.limiter importable"
else
    echo -e "  Library: ${RED}[X]${NC} src.limiter import failed"
fi

# Background process
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo -e "  Process: ${GREEN}[OK]${NC} Running (PID $PID)"
    else
        echo -e "  Process: ${YELLOW}[!]${NC} PID file exists but process not running"
    fi
else
    echo -e "  Process: ${YELLOW}[!]${NC} No background process (library mode - normal)"
fi
