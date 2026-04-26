# Contributing a FERAL Channel

> **Status: W21 Phase 1.** This document covers the manifest schema,
> the bundled-channel discovery loop, the W8 signing path, and the
> SDK-barrel architectural rule. It does **not** yet cover the full
> extension SDK (Phase 3 / W21.3) or 3rd-party path discovery
> (Phase 4 / W21.4) — those layers are sketched at the end of this
> document and will be filled in by their own PRs.

## 1. What a FERAL channel is

A **channel** is the bridge between FERAL and a messaging surface
(Telegram, Slack, Discord, WhatsApp, …). The runtime
implementation lives under `feral-core/channels/` and is built on the
abstract `Channel` base class in
[`feral-core/channels/base.py`](../feral-core/channels/base.py). As of
W21 Phase 1 every channel must also ship a **manifest** —
`feral-channel.manifest.json` — beside its adapter, declaring the
providers it speaks to, the env vars its auth needs, and the
capabilities it advertises.

The manifest is the seam that makes channels addressable from outside
the in-tree Python surface (CLI, Settings dropdown, capability planner,
3rd-party catalogs).

## 2. Manifest schema reference

Authoritative schema: [`feral-core/channels/manifest_schema.json`](../feral-core/channels/manifest_schema.json) (JSON Schema draft-07).

Required fields:

| Field | Type | Notes |
|---|---|---|
| `id` | string | `^[a-z][a-z0-9_-]*$`, ≤ 64 chars. Stable manifest id. |
| `providers` | array&lt;string&gt; | Underlying provider IDs (often `[id]`). |
| `providerAuthEnvVars` | object | Map *provider → list of env var names*. Keys MUST appear in `providers`. |
| `capabilities` | object&lt;string, bool&gt; | At least one capability MUST be `true`. Known keys: `messagingProvider`, `voiceProvider`, `fileProvider`, `webhookProvider`, `videoProvider`, `presenceProvider`. |

Optional fields:

| Field | Type | Notes |
|---|---|---|
| `providerAuthChoices` | array | Auth menu (`oauth` / `device-code` / `api-key`) modeled on openclaw's `providerAuthChoices`. |
| `modelSupport` | object | `modelPrefixes`, `preferredModels` — hint for the model picker. |
| `contracts` | object | Capability-contract version pins (e.g. `{"messaging": "v1"}`). |
| `signature` | object | Ed25519 signature envelope (see §4). |

Bundled example: [`feral-core/channels/telegram/feral-channel.manifest.json`](../feral-core/channels/telegram/feral-channel.manifest.json).

## 3. Adding a new in-tree channel (Phase 1 path)

Phase 1 only supports **bundled** manifests beside an existing in-tree
adapter. The full third-party SDK + entry-point discovery will land in
W21.3 / W21.4.

1. Implement the adapter under `feral-core/channels/<id>.py` (or a
   subpackage), subclassing `Channel` from `channels.base`.
2. Add the manifest at `feral-core/channels/<id>/feral-channel.manifest.json`.
3. Sign the manifest using
   `feral_core.channels.manifest.sign_manifest(...)` — see §4.
4. Register the adapter in
   `feral-core/tests/test_channel_manifest_contract.py`'s
   `_ADAPTER_BY_MANIFEST_ID` map so the contract test exercises it.
5. Run:

   ```bash
   cd feral-core
   python -m pytest tests/test_channel_manifest_*.py -v --no-cov
   ```

That's the full Phase-1 acceptance loop.

## 4. Signing a manifest

Manifests use the **same Ed25519 signer** W8 introduced for GenUI
manifests — `feral_core.genui.manifest_signing` (PyNaCl). The channel
manifest's signature envelope is shaped to match the rest of the
manifest (camelCase keys, ISO-8601 timestamp), but the bytes signed
are produced by `genui.manifest_signing.canonical_json(...)` over the
manifest dict **with the `signature` field removed**.

Programmatically:

```python
from feral_core.channels.manifest import sign_manifest, load_manifest_dict
from feral_core.genui.manifest_signing import generate_keypair

priv, pub = generate_keypair()
signed = sign_manifest(unsigned_dict, priv, public_key_id="my-publisher-key")
manifest = load_manifest_dict(signed)            # validates schema
ok, reason = manifest.is_signed, None
```

Verification:

```python
from feral_core.channels.manifest import verify_signature
ok, reason = verify_signature(manifest)          # trust embedded key
ok, reason = verify_signature(
    manifest,
    public_key_provider=lambda kid: vault.get(kid),  # pin via vault
)
```

The loader-level dial is `load_with_verification(allow_unsigned=...)`:

* `allow_unsigned=False` (default; production): unsigned manifests are
  refused; tampered signatures are refused.
* `allow_unsigned=True` (dev): unsigned manifests are accepted; tampered
  signatures are STILL refused. A present-but-broken signature is
  always fatal.

### W8 wire-contract reasons

`verify_signature` returns `(False, reason)` strings shared with W8:
`format_error:...`, `signature_mismatch`, `key_mismatch`,
`unsupported_alg:...`, `unsigned`. Tooling and the CLI rely on these
verbatim — do not rename them silently.

## 5. SDK-barrel rule (architectural boundary)

Modeled on openclaw's `AGENTS.md:27–30`:

> **Channel code reaches into core ONLY via `feral_core.channels.sdk`;
> everything else is private.** Core must not reach into channel
> internals; channels must not reach into core internals or into other
> channels' modules.

Phase 1 ships the manifest + loader + capability registry. The
`feral_core.channels.sdk` barrel itself is the **W21.3** deliverable.
For Phase 1 the rule applies prospectively: do not add `from
api.state import state` (or any other `feral-core/{api,services,...}`
import) into `feral-core/channels/manifest.py`,
`feral-core/channels/loader.py`, or any new bundled channel's adapter
beyond what the existing in-tree adapters already do. The Phase-3 SDK
will formalise the surface (typed runtime context, allowed helpers,
permitted re-exports); until then, treat anything not in `channels/`
as **off-limits for new channel code**.

## 6. Roadmap (Phases 2 / 3 / 4)

This document will grow as the W21.x sub-workstreams land:

| Phase | Workstream | Scope |
|---|---|---|
| 1 (this PR) | **W21** | Schema + loader + capability registry + signing glue + bundled Telegram example. |
| 2 | **W21.2** | Migrate Slack / Discord / WhatsApp manifests to the same shape; ship `feral-channel-sdk` barrel directory. |
| 3 | **W21.3** | Full extension SDK + typed runtime helpers + `provider-runtime.contract.test.py` family generic across channels. |
| 4 | **W21.4** | 3rd-party path discovery: entry-point loader, optional sandbox install path, vault-pinned publisher keys. |

Until Phase 4 lands, `discover_bundled()` and `load_with_verification()`
walk only the in-tree `feral-core/channels/<id>/` directories. The
public key embedded in a Phase-1 bundled manifest IS the trust root
for that manifest — appropriate because the manifest itself is
in-tree, reviewed via PR, and signed by a key documented in the PR
body.

## 7. Cross-references

* OPENCLAW lessons §5: [`docs/OPENCLAW_LESSONS.md`](OPENCLAW_LESSONS.md#5-plugin--extension--channel-model)
* W8 signing primitive: [`feral-core/genui/manifest_signing.py`](../feral-core/genui/manifest_signing.py)
* Existing channel base class: [`feral-core/channels/base.py`](../feral-core/channels/base.py)
