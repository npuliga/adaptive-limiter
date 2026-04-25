#!/usr/bin/env bash
# adaptive-limiter :: restart.sh
# Restarts the background demo process (if running).

set -euo pipefail

CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}[*] adaptive-limiter :: restart${NC}"

bash "$SCRIPT_DIR/stop.sh"
bash "$SCRIPT_DIR/start.sh" "${@}"
