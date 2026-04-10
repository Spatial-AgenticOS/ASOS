#!/usr/bin/env bash
# Build the THEORA web client and copy into asos-core/webui/ for bundled serving.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT="$ROOT/asos-client"
WEBUI="$ROOT/asos-core/webui"

echo "Building THEORA web client..."

if [ ! -d "$CLIENT" ]; then
    echo "Error: asos-client directory not found at $CLIENT"
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
echo "Start the server with: theora serve"
