#!/usr/bin/env bash
# adaptive-limiter :: start.sh
# Starts a demo run of the adaptive limiter library.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$SCRIPT_DIR/app.pid"
LOG_FILE="$SCRIPT_DIR/app.log"

echo -e "${CYAN}[*] adaptive-limiter${NC}"
echo ""
echo -e "${YELLOW}[!] This is a Python library / demo CLI - it does not run as a persistent server.${NC}"
echo ""
echo "To run the demo simulation:"
echo "  cd $APP_DIR"
echo "  python -m src.main"
echo "  python -m src.main --scenario traffic_spike"
echo "  python -m src.main --list-scenarios"
echo ""
echo "To use as a library:"
echo "  from src.limiter import AIMDController, ControllerConfig"
echo ""

# Optional: run demo in background if --background flag is set
if [[ "${1:-}" == "--background" ]]; then
    if [[ -f "$PID_FILE" ]]; then
        echo -e "${YELLOW}[!] Already running (PID $(cat $PID_FILE))${NC}"
        exit 0
    fi
    cd "$APP_DIR"
    PYTHON=$(command -v python3 || command -v python)
    nohup "$PYTHON" -m src.main >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo -e "${GREEN}[OK] Demo started in background (PID $(cat $PID_FILE))${NC}"
    echo "     Logs: $LOG_FILE"
fi
