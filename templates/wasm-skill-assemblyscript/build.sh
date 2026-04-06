#!/usr/bin/env bash
set -euo pipefail

# Build THEORA WASM skill (AssemblyScript)
# Prerequisites: npm install

echo "Building WASM skill (AssemblyScript)..."
mkdir -p build
npm run build

WASM_FILE="build/skill.wasm"
if [ -f "$WASM_FILE" ]; then
    echo "✓ Built: $WASM_FILE ($(du -h "$WASM_FILE" | cut -f1))"
    echo ""
    echo "To install:"
    echo "  cp $WASM_FILE ~/.theora/skills/wasm/"
else
    echo "✗ Build failed"
    exit 1
fi
