# feral-node-sdk

Official Python SDK for the FERAL **Hardware Unification Protocol (HUP v1)**.
See the full wire spec in [`../HUP_SPEC.md`](../HUP_SPEC.md).

```bash
pip install feral-node-sdk
```

## Minimal example

```python
import asyncio
from feral_node_sdk import FeralNode, capability

node = FeralNode(
    node_id="my-wristband",
    name="Acme Wristband",
    firmware_version="1.2.3",
    brain_url="wss://feral.local:9090/v1/node",
    api_key="fkn_live_...",
    capabilities=[capability.HEART_RATE, capability.BUZZER, capability.BATTERY],
    node_type="wearable",
)

@node.on_action("buzz")
async def buzz(params):
    duration_ms = params.get("duration_ms", 200)
    # TODO: drive the real haptic motor here
    return {"vibrated_ms": duration_ms}

async def loop():
    while True:
        await node.emit_event("heart_rate", {"bpm": 72})
        await asyncio.sleep(1.0)

node.run(loop())
```

## First-time pairing (CLI)

```bash
# 1. Launch the daemon once: it prints a 6-digit code.
python -m feral_node_sdk pair --node-id my-wristband --brain wss://feral.local:9090
#  → FERAL pairing code: 417 392
# 2. In the FERAL UI: Settings → Devices → Pair, type the code.
# 3. The SDK saves the API key to ~/.feral/node-keys/my-wristband.key and exits.
```

## Discovery

```python
from feral_node_sdk import FeralNode

brain_url = await FeralNode.discover_brain(timeout_s=3.0)
```

## What's in the box

- `FeralNode` — connection, auto-reconnect, heartbeat, action dispatch.
- `capability` — canonical capability enum (matches `HUP_SPEC.md` §5.1).
- `feral_node_sdk.schemas` — Pydantic mirrors of every wire schema.
- `feral_node_sdk.discovery` — mDNS/Zeroconf `_feral-brain._tcp.local.` finder.
- `feral_node_sdk.pairing` — 6-digit code exchange + on-disk key storage.
- `python -m feral_node_sdk pair ...` — shipable CLI.

All outgoing frames are validated against the schemas before send, so a
daemon built with this SDK is conformant by construction.
