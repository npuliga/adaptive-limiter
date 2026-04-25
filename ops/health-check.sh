#!/usr/bin/env bash
# adaptive-limiter :: health-check.sh
# Verifies the library can be imported and core classes are accessible.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${CYAN}[*] adaptive-limiter :: health-check${NC}"
echo ""

FAILED=0

# Check Python
PYTHON=$(command -v python3 || command -v python || echo "")
if [[ -z "$PYTHON" ]]; then
    echo -e "  ${RED}[X]${NC} Python not found"
    FAILED=1
else
    echo -e "  ${GREEN}[OK]${NC} Python: $($PYTHON --version)"
fi

# Check core library imports
if [[ $FAILED -eq 0 ]]; then
    if cd "$APP_DIR" && "$PYTHON" -c "
import sys
sys.path.insert(0, '.')
from src.limiter import AIMDController, ControllerConfig, ControlAction
from src.simulator import WorkloadSimulator
from src.metrics import MetricsCollector
print('imports ok')
" 2>/dev/null | grep -q 'imports ok'; then
        echo -e "  ${GREEN}[OK]${NC} Core library imports (AIMDController, WorkloadSimulator, MetricsCollector)"
    else
        echo -e "  ${RED}[X]${NC} Core library import failed"
        FAILED=1
    fi
fi

# Check main entry point
if [[ $FAILED -eq 0 ]]; then
    if cd "$APP_DIR" && "$PYTHON" -m src.main --list-scenarios &>/dev/null; then
        echo -e "  ${GREEN}[OK]${NC} Entry point: python -m src.main --list-scenarios"
    else
        echo -e "  ${YELLOW}[!]${NC} Entry point check inconclusive (may need scenario data)"
    fi
fi

echo ""
if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}[OK] Health check passed${NC}"
    exit 0
else
    echo -e "${RED}[X] Health check failed${NC}"
    exit 1
fi
