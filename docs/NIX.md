# Nix Quick Start

THEORA now includes a thin Nix foundation through `flake.nix`.

## What it provides

- `devShells.default`: Python + Node + Rust-capable development shell
- `packages.<system>.theora-brain`: wrapper that starts the brain with the runtime contract env
- `packages.<system>.theora-client`: wrapper that starts the Vite client
- `apps.brain` and `apps.client`: direct app entry points
- `nixosModules.theora-brain`: minimal service module for host-level enablement

## Common commands

```bash
# Enter dev shell
nix develop

# Run the brain app
nix run .#brain

# Build the brain package
nix build .#theora-brain

# Run the client app (requires node_modules in asos-client)
nix run .#client
```

## Runtime contract env vars

- `THEORA_HOME`
- `THEORA_HOST`
- `THEORA_PORT`
- `THEORA_PUBLIC_BASE_URL`

If not set, the wrappers default to local development values.
