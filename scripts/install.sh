#!/usr/bin/env bash
#
# THEORA Installer
# ================
# curl -sSL https://raw.githubusercontent.com/Spatial-AgenticOS/ASOS/main/scripts/install.sh | bash
#
# That's it. After this runs, you type: theora start
#
set -euo pipefail

BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║       T H E O R A  Installer         ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# ─── Check Python ───────────────────────────────────────

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &> /dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}  Python 3.11+ is required.${NC}"
    echo ""
    echo "  Install it:"
    echo "    macOS:  brew install python@3.12"
    echo "    Ubuntu: sudo apt install python3.12"
    echo "    Other:  https://python.org/downloads"
    exit 1
fi

echo -e "  ${GREEN}✓${NC} Python $($PYTHON --version 2>&1 | awk '{print $2}')"

# ─── Install ────────────────────────────────────────────

echo ""
echo -e "  Installing THEORA..."

# Detect if we're in the repo
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR=""
REPO_ROOT=""

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../asos-core/pyproject.toml" ]; then
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    echo -e "  ${DIM}From local repo: $REPO_ROOT${NC}"
    $PYTHON -m pip install -e "$REPO_ROOT/asos-core[llm]" --quiet 2>&1 | tail -3 || true
else
    $PYTHON -m pip install "theora-asos[llm]" --quiet 2>&1 | tail -1 || {
        echo -e "  ${DIM}Trying GitHub install...${NC}"
        $PYTHON -m pip install "theora-asos[llm] @ git+https://github.com/Spatial-AgenticOS/ASOS.git#subdirectory=asos-core" --quiet 2>&1 | tail -1 || {
            TMPDIR=$(mktemp -d)
            git clone --depth 1 https://github.com/Spatial-AgenticOS/ASOS.git "$TMPDIR/ASOS" 2>/dev/null
            $PYTHON -m pip install -e "$TMPDIR/ASOS/asos-core[llm]" --quiet
        }
    }
fi

# Verify
if command -v theora &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} theora command installed"
else
    echo -e "  ${YELLOW}⚠${NC} 'theora' not in PATH (try: $PYTHON -m cli.main)"
fi

# ─── Done ───────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}  Installed!${NC}"
echo ""

# Auto-run setup wizard if no credentials exist
THEORA_CREDS="$HOME/.theora/credentials.json"
if [ ! -f "$THEORA_CREDS" ] || [ ! -s "$THEORA_CREDS" ]; then
    echo -e "  ${BOLD}Let's set up your agent...${NC}"
    echo ""
    if command -v theora &> /dev/null; then
        theora setup
    else
        $PYTHON -m cli.setup_wizard 2>/dev/null || {
            echo -e "  ${DIM}Setup wizard not available. Run it later: theora setup${NC}"
        }
    fi
    echo ""
fi

echo -e "  ${BOLD}Start THEORA:${NC}"
echo "    theora start"
echo ""
echo -e "  ${BOLD}That's it.${NC} One command. Brain starts, dashboard opens, chat begins."
echo ""
echo -e "  ${DIM}Other commands:${NC}"
echo "    theora setup      # Re-run setup wizard"
echo "    theora doctor     # Check what's working"
echo "    theora serve      # Headless server mode"
echo ""
