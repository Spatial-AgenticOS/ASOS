# `feral-demo-data`

**Dev-only** demo data, simulators, and seeded scenarios for FERAL. This
package is **never** installed by `pip install feral-ai` — it ships
separately so the production brain has zero synthetic-biometric code
paths in the install footprint.

Use this when:

- Recording or replaying canned demo sessions (`.feral-demo` artifacts)
- Driving repeatable scripted scenarios for development
- Spinning up a wristband simulator + smart-home simulator without
  owning real hardware

Do **not** use this in production.

## Install

```bash
pip install feral-demo-data
# or
pip install feral-ai[demo]
```

Both pull `feral-ai` as a dependency. After install:

```bash
feral demo --scenario morning   # CLI entrypoint exposed via plugin
feral start --demo              # core CLI auto-detects this package
```

If `feral-demo-data` is **not** installed and you set
`FERAL_DEV_DEMO=1` (or run `feral demo`), the brain prints a clear
error explaining that the optional demo extras are missing — it
**never** silently no-ops.

## Architecture

```
feral-demo-data
├── simulator.py           WristbandSimulator, SmartHomeSimulator,
│                          DemoOrchestrator (telemetry loop)
├── scenarios.py           SCENARIO_* dicts + ScenarioRunner
├── seed.py                seed_demo_identity, seed_demo_memory
├── runner.py              run_demo() helper
└── cli.py                 `feral-demo` console entry point
```

`feral-demo-data` depends on `feral-ai`. `feral-ai` does **not**
depend on `feral-demo-data`. Discovery is one-way via
`entry_points(group="feral.plugins")`.
