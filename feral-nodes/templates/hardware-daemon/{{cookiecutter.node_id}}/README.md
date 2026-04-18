# {{cookiecutter.name}}

A FERAL HUP v1 daemon generated from the reference template.

## Getting started

```bash
pip install -e .
python -m feral_node_sdk pair --node-id {{cookiecutter.node_id}} --brain wss://feral.local:9090
python -m {{cookiecutter.node_id}}.daemon
```

## Pair (one-time)

`python -m feral_node_sdk pair ...` prints a 6-digit code. Type it into
the FERAL UI under **Settings → Devices → Pair**. The key is saved to
`~/.feral/node-keys/{{cookiecutter.node_id}}.key` and reused on every run.

## Publish

```bash
feral publish --daemon .
```

See the wire spec: [HUP_SPEC.md](../../HUP_SPEC.md).
