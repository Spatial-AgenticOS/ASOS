# @feral-ai/node-sdk

Official TypeScript / Node.js SDK for the FERAL **Hardware Unification
Protocol (HUP v1)**. Full wire spec: [`../HUP_SPEC.md`](../HUP_SPEC.md).

```bash
npm install @feral-ai/node-sdk
```

## Minimal example (20 lines)

```ts
import { FeralNode, Capability } from "@feral-ai/node-sdk";

const node = new FeralNode({
  nodeId: "my-wristband",
  name: "Acme Wristband",
  firmwareVersion: "1.2.3",
  brainUrl: "wss://feral.local:9090/v1/node",
  apiKey: process.env.FERAL_KEY,
  capabilities: [Capability.HEART_RATE, Capability.BUZZER, Capability.BATTERY],
  nodeType: "wearable",
});

node.onAction("buzz", async (params) => {
  const durationMs = Number(params.duration_ms ?? 200);
  // TODO: drive real haptic motor here
  return { vibrated_ms: durationMs };
});

await node.run(async () => {
  setInterval(() => node.emitEvent("heart_rate", { bpm: 72 }), 1000);
});
```

## First-time pairing

```bash
npx feral-node pair --node-id my-wristband --brain wss://feral.local:9090
# Prints a 6-digit code; type it in FERAL → Settings → Devices → Pair.
# The API key is saved to ~/.feral/node-keys/my-wristband.key (mode 0600).
```

## What's in the box

- `FeralNode` — connection, auto-reconnect, heartbeat, action dispatch.
- `Capability` — canonical enum, identical to Python SDK and `HUP_SPEC.md` §5.1.
- `schemas` — Zod mirrors of every wire schema; `buildFrame()` validates before send.
- `discoverBrain()` — mDNS finder for `_feral-brain._tcp.local.`.
- `pair()` — 6-digit code exchange + on-disk key storage.
- `feral-node` CLI — `pair`, `discover`, `key`.
