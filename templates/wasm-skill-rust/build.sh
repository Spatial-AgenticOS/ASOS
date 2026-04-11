#!/usr/bin/env bash
set -euo pipefail

# Build FERAL WASM skill (Rust)
# Prerequisites: rustup target add wasm32-wasi

echo "Building WASM skill..."
cargo build --target wasm32-wasi --release

WASM_FILE="target/wasm32-wasi/release/feral_skill_example.wasm"
if [ -f "$WASM_FILE" ]; then
    echo "✓ Built: $WASM_FILE ($(du -h "$WASM_FILE" | cut -f1))"
    echo ""
    echo "To install:"
    echo "  cp $WASM_FILE ~/.feral/skills/wasm/"
    echo "  # Add manifest.json alongside it"
else
    echo "✗ Build failed"
    exit 1
fi
