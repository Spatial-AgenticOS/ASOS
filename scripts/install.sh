#!/usr/bin/env bash
#
# THEORA One-Line Installer
# ==========================
# curl -sSL https://raw.githubusercontent.com/Spatial-AgenticOS/ASOS/main/scripts/install.sh | bash
#
set -euo pipefail

BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

VENV_DIR="$HOME/.theora-env"

echo -e "${BOLD}${CYAN}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║            T H E O R A  Installer                ║"
echo "  ║   Open AI Operating System · Privacy-First       ║"
echo "  ╚══════════════════════════════════════════════════╝"
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

# ─── Create Virtual Environment ──────────────────────────

if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ]; then
    echo -e "  ${GREEN}✓${NC} Virtual environment exists at $VENV_DIR"
else
    echo -e "  ${DIM}Creating virtual environment at $VENV_DIR ...${NC}"
    $PYTHON -m venv "$VENV_DIR" 2>/dev/null || {
        echo -e "  ${YELLOW}⚠${NC} Could not create venv, installing globally"
        VENV_DIR=""
    }
fi

if [ -n "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    PYTHON="$VENV_DIR/bin/python"
    echo -e "  ${GREEN}✓${NC} Activated virtual environment"
fi

$PYTHON -m pip install --upgrade pip --quiet 2>/dev/null || true

# ─── Install ────────────────────────────────────────────

echo ""
echo -e "  Installing THEORA..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR=""

PIP_LOG=$(mktemp /tmp/theora-pip-XXXXXX.log 2>/dev/null || echo "/tmp/theora-pip-install.log")

install_success=false

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../asos-core/pyproject.toml" ]; then
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    echo -e "  ${DIM}From local repo: $REPO_ROOT${NC}"
    if $PYTHON -m pip install --upgrade --force-reinstall -e "$REPO_ROOT/asos-core[llm]" 2>&1 | tee "$PIP_LOG" | tail -5; then
        install_success=true
    fi
else
    echo -e "  ${DIM}Installing from GitHub...${NC}"
    if $PYTHON -m pip install --upgrade --force-reinstall "theora-asos[llm] @ git+https://github.com/Spatial-AgenticOS/ASOS.git#subdirectory=asos-core" 2>&1 | tee "$PIP_LOG" | tail -5; then
        install_success=true
    else
        echo -e "  ${DIM}Git install failed. Trying PyPI...${NC}"
        if $PYTHON -m pip install --upgrade --force-reinstall "theora-asos[llm]" 2>&1 | tee "$PIP_LOG" | tail -5; then
            install_success=true
        else
            echo -e "  ${DIM}PyPI failed. Cloning repo...${NC}"
            TMPDIR=$(mktemp -d)
            if git clone --depth 1 https://github.com/Spatial-AgenticOS/ASOS.git "$TMPDIR/ASOS" 2>/dev/null; then
                if $PYTHON -m pip install --upgrade --force-reinstall -e "$TMPDIR/ASOS/asos-core[llm]" 2>&1 | tee "$PIP_LOG" | tail -5; then
                    install_success=true
                fi
            fi
        fi
    fi
fi

if [ "$install_success" = false ]; then
    echo ""
    echo -e "  ${RED}Installation failed.${NC}"
    echo -e "  ${DIM}Full log: $PIP_LOG${NC}"
    echo ""
    echo "  Common fixes:"
    echo "    1. Upgrade pip:  $PYTHON -m pip install --upgrade pip"
    echo "    2. Retry:        source ~/.theora-env/bin/activate && pip install theora-asos[llm]"
    echo "    3. Manual clone: git clone https://github.com/Spatial-AgenticOS/ASOS && cd ASOS/asos-core && pip install -e .[llm]"
    exit 1
fi

rm -f "$PIP_LOG" 2>/dev/null || true

# ─── Browser Runtime (best effort) ─────────────────────
echo -e "  ${DIM}Installing Playwright Chromium runtime (best effort)...${NC}"
$PYTHON -m playwright install chromium --with-deps >/dev/null 2>&1 || true

# ─── Installed Package Diagnostics ──────────────────────
PKG_INFO="$($PYTHON -m pip show theora-asos 2>/dev/null || true)"
if [ -n "$PKG_INFO" ]; then
    PKG_VERSION="$(printf '%s\n' "$PKG_INFO" | awk -F': ' '/^Version:/{print $2}')"
    PKG_LOCATION="$(printf '%s\n' "$PKG_INFO" | awk -F': ' '/^Location:/{print $2}')"
    if [ -n "${PKG_VERSION:-}" ]; then
        echo -e "  ${GREEN}✓${NC} Installed package: theora-asos ${PKG_VERSION}"
    fi
    if [ -n "${PKG_LOCATION:-}" ]; then
        echo -e "  ${DIM}Location: ${PKG_LOCATION}${NC}"
    fi
fi

# ─── Verify CLI ─────────────────────────────────────────

echo ""
if command -v theora &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} theora command available"
else
    echo -e "  ${YELLOW}⚠${NC} 'theora' not found in PATH"
    if [ -n "$VENV_DIR" ]; then
        echo -e "  ${DIM}Activate your env first: source ~/.theora-env/bin/activate${NC}"
    else
        echo -e "  ${DIM}Try: $PYTHON -m cli.main${NC}"
    fi
fi

# ─── First-Time Setup ──────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}  Installed!${NC}"
echo ""

THEORA_CREDS="$HOME/.theora/credentials.json"
if [ ! -f "$THEORA_CREDS" ] || [ ! -s "$THEORA_CREDS" ]; then
    echo -e "  ${BOLD}First-time setup — let's configure your agent.${NC}"
    echo ""
    echo -e "  ${DIM}You can do this two ways:${NC}"
    echo ""
    echo -e "  ${CYAN}Option A: Terminal wizard (quick, 2 minutes)${NC}"
    echo "    theora setup"
    echo ""
    echo -e "  ${CYAN}Option B: Web UI wizard (full configuration)${NC}"
    echo "    theora serve"
    echo "    Then open http://localhost:9090 — the setup wizard starts automatically."
    echo ""

    read -r -p "  Run the terminal wizard now? [Y/n] " answer </dev/tty 2>/dev/null || answer="y"
    answer=${answer:-y}

    if [[ "$answer" =~ ^[Yy]$ ]]; then
        if command -v theora &> /dev/null; then
            theora setup
        else
            $PYTHON -m cli.setup_wizard 2>/dev/null || {
                echo -e "  ${DIM}Wizard not available. Start with: theora serve${NC}"
            }
        fi
    else
        echo ""
        echo -e "  ${DIM}No problem. Run 'theora serve' and configure via the web UI.${NC}"
    fi
    echo ""
fi

# ─── Post-Install Summary ──────────────────────────────

echo -e "  ${BOLD}┌──────────────────────────────────────────────┐${NC}"
echo -e "  ${BOLD}│  Start THEORA:                               │${NC}"
echo -e "  ${BOLD}│                                              │${NC}"
if [ -n "$VENV_DIR" ]; then
echo -e "  ${BOLD}│    source ~/.theora-env/bin/activate         │${NC}"
fi
echo -e "  ${BOLD}│    theora start                              │${NC}"
echo -e "  ${BOLD}│                                              │${NC}"
echo -e "  ${BOLD}│  Brain + dashboard at localhost:9090          │${NC}"
echo -e "  ${BOLD}└──────────────────────────────────────────────┘${NC}"
echo ""
echo -e "  ${DIM}Other commands:${NC}"
echo "    theora setup      Re-run setup wizard"
echo "    theora doctor     Check what's working"
echo "    theora serve      Headless server mode"
echo "    theora status     Current brain status"
echo ""
