"""
THEORA SDK — Build plugins, tools, device adapters, and GenUI components.

Quick start:

    from theora_sdk import TheoraPlugin, theora_tool, TheoraClient

    class MyPlugin(TheoraPlugin):
        name = "my-plugin"

        @theora_tool(description="Say hello")
        async def greet(self, name: str) -> dict:
            return {"message": f"Hello, {name}!"}
"""

__version__ = "0.1.0"

from theora_sdk.plugin import TheoraPlugin
from theora_sdk.tool import theora_tool
from theora_sdk.client import TheoraClient
from theora_sdk.device import HUPDevice
from theora_sdk.manifest import SkillManifest, Endpoint, Parameter
from theora_sdk.genui import GenUIComponent, GenUICard, GenUIMetric

__all__ = [
    "TheoraPlugin",
    "theora_tool",
    "TheoraClient",
    "HUPDevice",
    "SkillManifest",
    "Endpoint",
    "Parameter",
    "GenUIComponent",
    "GenUICard",
    "GenUIMetric",
]
