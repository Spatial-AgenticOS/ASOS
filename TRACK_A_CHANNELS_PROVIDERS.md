# Track A — Channels + LLM Providers (Weeks 5-7)

> Runs in parallel with tracks B/C/D after v2 ships. Closes the single
> biggest cohort-reach gap in `STATE_OF_FERAL.md § 4`: FERAL has 4
> channels vs OpenClaw's 15+, and 4 providers vs OpenClaw's 30+.
>
> Every channel + provider in this track follows the same shipped
> template. Each is ~1-3 days of real work for one engineer.

## Why not merge all of Track A into one commit

Each channel / provider needs live credentials + a real round-trip
test before we ship it — per the "never fake / never claim something
works until you've verified end-to-end" rules in
[`ASOS/AGENT_PROMPT.md`](AGENT_PROMPT.md). Shipping 11 integrations
without credentialed verification would violate that rule.

The honest path: ship one at a time, each a self-contained PR that
includes (a) implementation, (b) at least one live-round-trip test on
the maintainer's account, (c) a registry `kind=channel` / `kind=provider`
seed, (d) a docs page, (e) a changelog entry.

## Shared template

Every channel PR includes these files (referenced by OpenAI/OpenRouter
patterns already in-tree):

- `feral-core/channels/<name>.py` — subclass of `Channel` from
  [`feral-core/channels/base.py`](feral-core/channels/base.py). Must
  implement `start`, `stop`, `send`, and `channel_type`. `TelegramChannel`
  at line 182 of that file is the canonical reference.
- `feral-core/tests/test_channel_<name>.py` — unit + one round-trip
  contract test gated behind `FERAL_LIVE_<NAME>_TEST=1` so CI skips
  live-credential paths.
- `feral-registry/scripts/seed_<name>.py` — `kind=channel` item registered
  under publisher `feral`, Ed25519-signed via existing seeding flow.
- `docs/mintlify/channels/<name>.mdx` — setup guide + token location.

Every provider PR includes:

- `feral-core/providers/<name>_provider.py` — subclass of `Provider`
  Protocol from [`feral-core/providers/base.py`](feral-core/providers/base.py).
  Existing `groq_provider.py` + `deepseek_provider.py` are the references.
- `feral-core/tests/test_providers.py` — existing contract test. Add your
  provider to the parametrised fixture.
- Add the provider's `[provider-<name>]` extra in
  [`feral-core/pyproject.toml`](feral-core/pyproject.toml).
- Schedule `scripts/research_providers.py` to fetch the public model
  catalog (or hand-curate in `providers/model_catalog.json` for
  providers with no `/v1/models` endpoint).

## Channel PR list (weeks 5 + 7)

| # | Channel | Week | Owner | Notes | Status |
|---|---------|------|-------|-------|--------|
| 1 | Matrix | 5 | — | `matrix-nio` SDK; homeserver URL + access token in config | **EXEMPLAR SHIPPED (stub)** — see [`feral-core/channels/matrix.py`](feral-core/channels/matrix.py) |
| 2 | Signal | 5 | — | `signald` or `signal-cli` daemon; unregistered state handled | todo |
| 3 | Voice Call | 5 | — | Twilio Voice or Vonage; inbound webhook → STT → brain → TTS → twiml | todo |
| 4 | WhatsApp Business | 7 | — | Meta Graph API v18; webhook verification required | todo |
| 5 | Feishu | 7 | — | `open.feishu.cn` bot + approval events | todo |
| 6 | Zalo | 7 | — | Zalo Official Account API; OA access token | todo |

## Provider PR list (week 6)

| # | Provider | Extra | Model catalog | Status |
|---|----------|-------|---------------|--------|
| 1 | Groq | `[provider-groq]` | `/v1/models` live | **ALREADY SHIPPED** per `CHANGELOG.md` 2026.4.14 |
| 2 | DeepSeek | `[provider-deepseek]` | `/v1/models` live | **ALREADY SHIPPED** per `CHANGELOG.md` 2026.4.14 |
| 3 | Together | `[provider-together]` | `/v1/models` live | todo |
| 4 | OpenRouter | `[provider-openrouter]` | `/api/v1/models` live | todo |
| 5 | Bedrock | `[provider-bedrock]` | Hand-curated (AWS no public API) | todo |
| 6 | Fireworks | `[provider-fireworks]` | `/v1/models` live | todo |

## Success criteria

When Track A is closed, the comparison row in
[`STATE_OF_FERAL.md § 3.1`](STATE_OF_FERAL.md) reads:

> Channels shipped today: 10 fully-wired (Telegram, Discord, Slack,
> WhatsApp, Matrix, Signal, Voice Call, WhatsApp Business, Feishu, Zalo)

> LLM providers: 10 first-party (OpenAI, Anthropic, Gemini, Ollama, Groq,
> DeepSeek, Together, OpenRouter, Bedrock, Fireworks)

…and `registry.feral.sh` shows `kind=channel` + `kind=provider` items
populated (currently `kind=provider` has 2 items per the seed, `kind=channel`
has 0).

## Exemplar: Matrix channel stub

[`feral-core/channels/matrix.py`](feral-core/channels/matrix.py) is the
only honest thing a same-turn agent can ship without a Matrix
homeserver to verify against: a stub that implements the `Channel`
interface, refuses to fake a connection when credentials are missing,
and documents exactly what the follow-up PR must add. The full Matrix
implementation is the template every remaining channel in this track
follows.
