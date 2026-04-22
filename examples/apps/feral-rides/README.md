# feral-rides

Ride-request example showing authored + hybrid surfaces with destructive-action confirmations.

## What it proves

* Authored `request` form gathers pickup + destination, emits `{values: {...}}` via the unified `ui_event` contract.
* Hybrid `confirm` surface ships a publisher template; the agent can regenerate a personalised version on the fly using the InteractionRules + brand color when `regenerate=true` is requested.
* Destructive `cancel_ride` action is contract-marked `requires_confirmation: true`, so the brain's dispatcher and v2's renderer agree to gate it behind a Modal.
* Map / progress bar primitives demonstrate the SDUI renderer placeholders gracefully degrading in v2 until a future renderer ships native widgets.

## Install + run

```sh
feral app validate ./
feral app install ./
open http://localhost:9090/apps/feral-rides
```
