# FERAL Hardware Daemon Template

Fork-and-fill skeleton for a vendor-built HUP v1 daemon. Two ways to use it:

## Option A — cookiecutter

```bash
pip install cookiecutter
cookiecutter ASOS/feral-nodes/templates/hardware-daemon/
```

Cookiecutter will ask for `node_id`, `name`, `firmware_version`, `node_type`,
`capabilities` (comma list), `author`, `manufacturer`.

## Option B — plain copy

```bash
cp -r ASOS/feral-nodes/templates/hardware-daemon/{{cookiecutter.node_id}} my_daemon
# then open my_daemon/ and replace every {{cookiecutter.*}} placeholder.
```

## What to edit

- `src/<node_id>/daemon.py` — the ~50-line scaffold. TODO markers show
  where to plug in your real hardware calls. Everything outside the TODOs
  is already conformant with [`../../HUP_SPEC.md`](../../HUP_SPEC.md).
- `manifest.json` — the `DaemonManifest` shape consumed by
  `feral publish --daemon`.
- `pyproject.toml` — bump `version`, pin your own deps.

## Publishing

```bash
feral publish --daemon .         # uploads manifest + wheel to the registry
feral install <node_id>          # on the target machine
python -m feral_node_sdk pair --node-id <node_id> --brain wss://feral.local:9090
```
