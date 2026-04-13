# feral-sdk (Python)

Python SDK for building FERAL plugins, tools, device adapters, and GenUI components.

## Installation

```bash
pip install feral-sdk
```

Or install from source during development:

```bash
pip install -e sdk/python
```

## Quick start

```python
from feral_sdk import FeralPlugin, feral_tool

class WeatherPlugin(FeralPlugin):
    name = "weather"
    description = "Real-time weather data"

    @feral_tool(description="Get current weather for a city")
    async def current(self, city: str) -> dict:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.weatherapi.com/v1/current.json",
                params={"key": "YOUR_KEY", "q": city},
            )
            return resp.json()
```

### Generating a manifest

```python
plugin = WeatherPlugin()
manifest = plugin.to_manifest()   # dict ready for manifest.json
```

The manifest uses `internal://` URLs with method `PYTHON`, which tells the
Brain's SkillExecutor to resolve the call through the registered Python
implementation rather than making an HTTP request.

### Registering with the Brain

Place your plugin module as `impl.py` inside the skill directory
(`~/.feral/skills/<skill_id>/`) alongside `manifest.json`, or call
`register_instance()` at startup:

```python
from skills.impl import register_instance

plugin = WeatherPlugin()
register_instance(plugin.name, plugin)
```

## Key modules

| Module | Purpose |
|--------|---------|
| `feral_sdk.plugin` | `FeralPlugin` base class |
| `feral_sdk.tool` | `@feral_tool` decorator |
| `feral_sdk.client` | `FeralClient` for talking to a running Brain |
| `feral_sdk.device` | `HUPDevice` base for hardware adapters |
| `feral_sdk.manifest` | `SkillManifest`, `Endpoint`, `Parameter` dataclasses |
| `feral_sdk.genui` | GenUI component helpers |

## Requirements

- Python >= 3.11
- httpx, websockets, pydantic (installed automatically)

## License

Apache-2.0
