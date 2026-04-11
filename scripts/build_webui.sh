#!/usr/bin/env bash
# Build the FERAL web client and copy into feral-core/webui/ for bundled serving.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT="$ROOT/feral-client"
WEBUI="$ROOT/feral-core/webui"

echo "Building FERAL web client..."

if [ ! -d "$CLIENT" ]; then
    echo "Error: feral-client directory not found at $CLIENT"
    exit 1
fi

cd "$CLIENT"

if [ ! -d node_modules ]; then
    echo "Installing dependencies..."
    npm install
fi

# Build with the correct API base — when bundled, the API is on the same origin
VITE_API_BASE="" npm run build

echo "Copying build output to $WEBUI..."
rm -rf "$WEBUI"
cp -r dist "$WEBUI"

# Add __init__.py markers so setuptools includes webui as a package
touch "$WEBUI/__init__.py"
mkdir -p "$WEBUI/assets"
touch "$WEBUI/assets/__init__.py"

echo "Done. Web UI bundled at $WEBUI"
echo "Start the server with: feral serve"
