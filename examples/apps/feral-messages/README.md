# feral-messages

Tiny example messaging app showing the FERAL GenUI third-party app contract end-to-end.

## What it proves

* Authored surfaces (`inbox`, `thread`) hydrate from live brain-side data via `$data.*` placeholders.
* Form submit emits `{values: {...}}` back through the `ui_event` pipe with the publisher's `app_id` scoping.
* Action contract validation rejects any action the publisher didn't declare in `action_contract`.
* Brand-aware rendering — outgoing message bubbles take `brand.primary_color`.

## Install locally

```sh
feral app validate ./
feral app install ./
```

Then open `http://localhost:9090/apps/feral-messages` in v2.

## Publish

```sh
feral publisher login
feral app publish ./
```

The signed bundle lands on `registry.feral.sh` under `kind=app`.
