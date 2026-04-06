#!/usr/bin/env bash
set -euo pipefail

# THEORA CLI Demo — interactive terminal agent
# Usage: bash scripts/demo_cli.sh
# Requires: Brain running (docker compose up or native)

BOLD='\033[1m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

cd "$(dirname "$0")/../asos-core"

# Check Brain is running
if ! curl -sf http://localhost:9090/ >/dev/null 2>&1; then
  echo -e "  ${RED}✗${NC} Brain is not running at localhost:9090"
  echo "  Start it first: docker compose up -d  OR  cd asos-core && PYTHONPATH=. python api/server.py"
  exit 1
fi
echo -e "  ${GREEN}✓${NC} Brain is running"

# Install if needed
if ! command -v theora &>/dev/null; then
  echo -e "  Installing THEORA CLI..."
  pip install -e . -q
fi

echo -e "\n  ${BOLD}Starting THEORA CLI...${NC}\n"
exec theora "$@"
