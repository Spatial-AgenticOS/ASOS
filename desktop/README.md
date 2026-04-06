# THEORA Desktop

Native desktop app wrapping the THEORA web UI via [Tauri 2](https://v2.tauri.app/).

## Requirements

- [Rust toolchain](https://rustup.rs/) (1.77+)
- Node.js 18+
- Tauri CLI: `cargo install tauri-cli`
- Platform build tools (Xcode on macOS, Visual Studio on Windows)

## Development

```bash
npm install
npm run tauri:dev
```

This starts both the Vite dev server and the Tauri window.

## Build

```bash
npm run tauri:build
```

Produces:
- macOS: `src-tauri/target/release/bundle/dmg/THEORA_1.0.0_*.dmg`
- Linux: `src-tauri/target/release/bundle/appimage/THEORA_1.0.0_*.AppImage`
- Windows: `src-tauri/target/release/bundle/msi/THEORA_1.0.0_*.msi`

## Architecture

The desktop app loads the Brain's web UI (`http://localhost:9090`) in a native window. Make sure the Brain server is running (`theora serve`) before launching.

Features:
- System tray icon (click to show/hide)
- Auto-detect Brain server health
- Native window with full webcam, voice, and tool access
