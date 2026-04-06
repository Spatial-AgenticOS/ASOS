#!/usr/bin/env bash
#
# THEORA Installer
# ================
# One command: curl -sSL https://raw.githubusercontent.com/Spatial-AgenticOS/ASOS/main/scripts/install.sh | bash
#
# What this does:
#   1. Checks Python 3.11+
#   2. pip installs theora from GitHub (or locally if run from repo)
#   3. Runs the guided setup wizard
#   4. Shows you how to start
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
    echo -e "${RED}Error: Python 3.11+ is required but not found.${NC}"
    echo ""
    echo "  Install Python:"
    echo "    macOS:  brew install python@3.12"
    echo "    Ubuntu: sudo apt install python3.12 python3.12-venv"
    echo "    Other:  https://python.org/downloads"
    exit 1
fi

echo -e "  ${GREEN}✓${NC} Python: $($PYTHON --version)"

# ─── Check pip ──────────────────────────────────────────

PIP="$PYTHON -m pip"
if ! $PIP --version &> /dev/null; then
    echo -e "${RED}Error: pip not found.${NC}"
    echo "  Install: $PYTHON -m ensurepip --upgrade"
    exit 1
fi

echo -e "  ${GREEN}✓${NC} pip available"

# ─── Install THEORA ─────────────────────────────────────

echo ""
echo -e "  ${BOLD}Installing THEORA...${NC}"

# If running from inside the repo, install locally
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR=""
REPO_ROOT=""

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../asos-core/pyproject.toml" ]; then
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    echo -e "  ${DIM}Installing from local repo: $REPO_ROOT${NC}"
    $PIP install -e "$REPO_ROOT/asos-core[llm]" --quiet 2>&1 | tail -1 || true
else
    echo -e "  ${DIM}Installing from GitHub...${NC}"
    $PIP install "theora[llm] @ git+https://github.com/Spatial-AgenticOS/ASOS.git#subdirectory=asos-core" --quiet 2>&1 | tail -1 || {
        echo -e "${YELLOW}pip install from git failed. Trying clone method...${NC}"
        TMPDIR=$(mktemp -d)
        git clone --depth 1 https://github.com/Spatial-AgenticOS/ASOS.git "$TMPDIR/ASOS"
        $PIP install -e "$TMPDIR/ASOS/asos-core[llm]" --quiet
    }
fi

# Verify installation
if ! command -v theora &> /dev/null; then
    THEORA_CMD="$PYTHON -m cli.main"
    echo -e "  ${YELLOW}⚠${NC} 'theora' command not in PATH. Using: $THEORA_CMD"
else
    THEORA_CMD="theora"
    echo -e "  ${GREEN}✓${NC} theora command installed"
fi

# ─── Run Setup Wizard ──────────────────────────────────

echo ""
echo -e "  ${BOLD}Running setup wizard...${NC}"
echo ""

$THEORA_CMD setup || $PYTHON -c "from cli.setup_wizard import run_setup; run_setup()" || {
    echo -e "  ${YELLOW}⚠${NC} Setup wizard failed. You can run it later: theora setup"
}

# ─── Done ───────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}  Installation complete!${NC}"
echo ""
echo -e "  ${BOLD}Start the agent:${NC}"
echo "    theora serve          # Start the server (port 9090)"
echo "    theora                # Interactive chat"
echo '    theora "what time is it"  # One-shot command'
echo ""
echo -e "  ${BOLD}Other commands:${NC}"
echo "    theora setup          # Re-run setup wizard"
echo "    theora status         # System health"
echo "    theora skills         # List available tools"
echo ""
echo -e "  ${DIM}Docs: https://github.com/Spatial-AgenticOS/ASOS${NC}"
echo ""
