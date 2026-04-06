#!/usr/bin/env bash
set -euo pipefail

# Build THEORA WASM skill (Rust)
# Prerequisites: rustup target add wasm32-wasi

echo "Building WASM skill..."
cargo build --target wasm32-wasi --release

WASM_FILE="target/wasm32-wasi/release/theora_skill_example.wasm"
if [ -f "$WASM_FILE" ]; then
    echo "✓ Built: $WASM_FILE ($(du -h "$WASM_FILE" | cut -f1))"
    echo ""
    echo "To install:"
    echo "  cp $WASM_FILE ~/.theora/skills/wasm/"
    echo "  # Add manifest.json alongside it"
else
    echo "✗ Build failed"
    exit 1
fi
