# Nix Quick Start

FERAL now includes a thin Nix foundation through `flake.nix`.

## What it provides

- `devShells.default`: Python + Node + Rust-capable development shell
- `packages.<system>.feral-brain`: wrapper that starts the brain with the runtime contract env
- `packages.<system>.feral-client`: wrapper that starts the Vite client
- `apps.brain` and `apps.client`: direct app entry points
- `nixosModules.feral-brain`: minimal service module for host-level enablement

## Common commands

```bash
# Enter dev shell
nix develop

# Run the brain app
nix run .#brain

# Build the brain package
nix build .#feral-brain

# Run the client app (requires node_modules in feral-client)
nix run .#client
```

## Runtime contract env vars

- `FERAL_HOME`
- `FERAL_HOST`
- `FERAL_PORT`
- `FERAL_PUBLIC_BASE_URL`

If not set, the wrappers default to local development values.
