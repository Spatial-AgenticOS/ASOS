#!/usr/bin/env bash
#
# THEORA — Spatial Agentic OS Installer
# ========================================
# Installs THEORA as a system service on Linux.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Spatial-AgenticOS/ASOS/main/scripts/install.sh | bash
#   # or locally:
#   ./scripts/install.sh
#
# What it does:
#   1. Creates XDG-compliant directories (~/.config/theora, ~/.local/share/theora)
#   2. Installs Python dependencies
#   3. Installs the `theora` CLI command
#   4. Sets up systemd user service (Linux) or launchd (macOS)
#   5. Builds the client UI
#   6. Opens the setup wizard in the browser

set -euo pipefail

BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

THEORA_VERSION="0.4.0"

echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║     THEORA Installer v${THEORA_VERSION}         ║"
echo "  ║   Spatial Agentic Operating System   ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# ─── Detect OS ───
OS="$(uname -s)"
ARCH="$(uname -m)"
echo -e "${DIM}Detected: ${OS} ${ARCH}${NC}"

# ─── Paths ───
if [ -n "${XDG_CONFIG_HOME:-}" ]; then
    THEORA_CONFIG="${XDG_CONFIG_HOME}/theora"
else
    THEORA_CONFIG="${HOME}/.config/theora"
fi

if [ -n "${XDG_DATA_HOME:-}" ]; then
    THEORA_DATA="${XDG_DATA_HOME}/theora"
else
    THEORA_DATA="${HOME}/.local/share/theora"
fi

THEORA_HOME="${HOME}/.theora"
INSTALL_DIR="${THEORA_DATA}/asos"
BIN_DIR="${HOME}/.local/bin"

# ─── Step 1: Create directories ───
echo -e "\n${CYAN}[1/6]${NC} Creating directories..."
mkdir -p "${THEORA_CONFIG}"
mkdir -p "${THEORA_DATA}"
mkdir -p "${THEORA_HOME}/skills"
mkdir -p "${BIN_DIR}"

# Symlink for backward compat (~/.theora → XDG config)
if [ ! -L "${THEORA_HOME}/settings.json" ] && [ ! -f "${THEORA_HOME}/settings.json" ]; then
    echo '{}' > "${THEORA_HOME}/settings.json"
fi
echo -e "  ${GREEN}✓${NC} ${THEORA_CONFIG}"
echo -e "  ${GREEN}✓${NC} ${THEORA_DATA}"
echo -e "  ${GREEN}✓${NC} ${THEORA_HOME}/skills/"

# ─── Step 2: Clone or update ASOS ───
echo -e "\n${CYAN}[2/6]${NC} Installing ASOS core..."
if [ -d "${INSTALL_DIR}/.git" ]; then
    echo "  Updating existing installation..."
    cd "${INSTALL_DIR}" && git pull --quiet
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    if [ -f "${SCRIPT_DIR}/asos-core/pyproject.toml" ]; then
        echo "  Linking from local checkout..."
        ln -sfn "${SCRIPT_DIR}" "${INSTALL_DIR}"
    else
        echo "  Cloning from GitHub..."
        git clone --quiet https://github.com/Spatial-AgenticOS/ASOS.git "${INSTALL_DIR}"
    fi
fi
echo -e "  ${GREEN}✓${NC} ASOS at ${INSTALL_DIR}"

# ─── Step 3: Install Python dependencies ───
echo -e "\n${CYAN}[3/6]${NC} Installing Python dependencies..."
cd "${INSTALL_DIR}/asos-core"
if command -v pip3 &> /dev/null; then
    pip3 install -e ".[dev]" --quiet 2>/dev/null || pip3 install -e . --quiet
    echo -e "  ${GREEN}✓${NC} Python packages installed"
else
    echo -e "  ${YELLOW}⚠${NC} pip3 not found — install Python 3.11+ and retry"
fi

# ─── Step 4: Install CLI ───
echo -e "\n${CYAN}[4/6]${NC} Installing CLI..."
cat > "${BIN_DIR}/theora" << 'THEORA_CLI'
#!/usr/bin/env bash
# THEORA CLI — Spatial Agentic OS
set -euo pipefail

THEORA_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/theora"
INSTALL_DIR="${THEORA_DATA}/asos"

case "${1:-help}" in
    start)
        echo "Starting THEORA Brain..."
        cd "${INSTALL_DIR}/asos-core"
        exec python3 -m uvicorn api.server:app --host 0.0.0.0 --port "${THEORA_PORT:-9090}" --log-level info
        ;;
    stop)
        echo "Stopping THEORA Brain..."
        pkill -f "uvicorn api.server:app" 2>/dev/null || echo "Not running."
        ;;
    status)
        if curl -s http://localhost:${THEORA_PORT:-9090}/ > /dev/null 2>&1; then
            echo "THEORA Brain is running"
            curl -s "http://localhost:${THEORA_PORT:-9090}/" | python3 -m json.tool 2>/dev/null || true
        else
            echo "THEORA Brain is not running"
        fi
        ;;
    setup)
        echo "Opening setup wizard..."
        if command -v xdg-open &> /dev/null; then
            xdg-open "http://localhost:${THEORA_PORT:-9090}/setup"
        elif command -v open &> /dev/null; then
            open "http://localhost:${THEORA_PORT:-9090}/setup"
        else
            echo "Open http://localhost:${THEORA_PORT:-9090}/setup in your browser"
        fi
        ;;
    daemon)
        echo "Starting W300 daemon..."
        cd "${INSTALL_DIR}/asos-nodes/python-node-sdk"
        exec python3 w300_daemon.py "${@:2}"
        ;;
    config)
        echo "Configuration:"
        echo "  Config: ${XDG_CONFIG_HOME:-$HOME/.config}/theora/"
        echo "  Data:   ${THEORA_DATA}/"
        echo "  Skills: ${HOME}/.theora/skills/"
        echo "  Memory: ${HOME}/.theora/memory.db"
        if [ -f "${HOME}/.theora/settings.json" ]; then
            cat "${HOME}/.theora/settings.json" | python3 -m json.tool 2>/dev/null || cat "${HOME}/.theora/settings.json"
        fi
        ;;
    logs)
        journalctl --user -u theora-brain -f 2>/dev/null || echo "systemd logs not available. Run 'theora start' to see output."
        ;;
    version)
        echo "THEORA v0.4.0 — Spatial Agentic OS"
        ;;
    help|--help|-h)
        echo "THEORA — Spatial Agentic OS"
        echo ""
        echo "Usage: theora <command>"
        echo ""
        echo "Commands:"
        echo "  start       Start the THEORA Brain server"
        echo "  stop        Stop the THEORA Brain server"
        echo "  status      Check if the brain is running"
        echo "  setup       Open the setup wizard in browser"
        echo "  daemon      Start a hardware daemon (e.g., W300 glasses)"
        echo "  config      Show current configuration paths and values"
        echo "  logs        View systemd logs (Linux)"
        echo "  version     Show version"
        echo ""
        echo "Environment:"
        echo "  THEORA_PORT   Brain port (default: 9090)"
        echo "  THEORA_HOME   Config directory (default: ~/.theora)"
        ;;
    *)
        echo "Unknown command: $1 (try 'theora help')"
        exit 1
        ;;
esac
THEORA_CLI
chmod +x "${BIN_DIR}/theora"
echo -e "  ${GREEN}✓${NC} ${BIN_DIR}/theora"

# ─── Step 5: Install systemd service (Linux) or launchd (macOS) ───
echo -e "\n${CYAN}[5/6]${NC} Installing system service..."

if [ "${OS}" = "Linux" ]; then
    SYSTEMD_DIR="${HOME}/.config/systemd/user"
    mkdir -p "${SYSTEMD_DIR}"

    cat > "${SYSTEMD_DIR}/theora-brain.service" << EOF
[Unit]
Description=THEORA Brain — Spatial Agentic OS
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}/asos-core
ExecStart=${BIN_DIR}/theora start
Restart=on-failure
RestartSec=5
Environment=THEORA_HOME=${THEORA_HOME}
Environment=XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-${HOME}/.config}
Environment=XDG_DATA_HOME=${XDG_DATA_HOME:-${HOME}/.local/share}

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} ${SYSTEMD_DIR}/theora-brain.service"
    echo -e "  ${DIM}  Enable with: systemctl --user enable --now theora-brain${NC}"

elif [ "${OS}" = "Darwin" ]; then
    LAUNCHD_DIR="${HOME}/Library/LaunchAgents"
    mkdir -p "${LAUNCHD_DIR}"

    cat > "${LAUNCHD_DIR}/com.theora.brain.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.theora.brain</string>
    <key>ProgramArguments</key>
    <array>
        <string>${BIN_DIR}/theora</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>${THEORA_DATA}/brain.log</string>
    <key>StandardErrorPath</key>
    <string>${THEORA_DATA}/brain.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>THEORA_HOME</key>
        <string>${THEORA_HOME}</string>
    </dict>
</dict>
</plist>
EOF
    echo -e "  ${GREEN}✓${NC} ${LAUNCHD_DIR}/com.theora.brain.plist"
    echo -e "  ${DIM}  Enable with: launchctl load ~/Library/LaunchAgents/com.theora.brain.plist${NC}"
fi

# ─── Step 6: Build client (if Node is available) ───
echo -e "\n${CYAN}[6/6]${NC} Building client UI..."
if command -v npm &> /dev/null; then
    cd "${INSTALL_DIR}/asos-client"
    npm install --quiet 2>/dev/null
    npm run build --quiet 2>/dev/null
    echo -e "  ${GREEN}✓${NC} Client built at ${INSTALL_DIR}/asos-client/dist/"
else
    echo -e "  ${YELLOW}⚠${NC} npm not found — client build skipped (install Node.js 18+)"
fi

# ─── PATH check ───
if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
    echo -e "\n${YELLOW}⚠${NC} ${BIN_DIR} is not in your PATH. Add this to your shell rc:"
    echo -e "  ${DIM}export PATH=\"\${HOME}/.local/bin:\${PATH}\"${NC}"
fi

echo -e "\n${GREEN}${BOLD}Installation complete!${NC}\n"
echo -e "  ${BOLD}Quick start:${NC}"
echo "    theora start      # Start the brain"
echo "    theora setup      # Open setup wizard"
echo "    theora status     # Check health"
echo ""
echo -e "  ${BOLD}Docker:${NC}"
echo "    docker compose up --build"
echo ""
echo -e "  ${BOLD}Docs:${NC} https://github.com/Spatial-AgenticOS/ASOS"
echo ""
