"""Smoke tests for the public ``feral_sdk`` package.

These intentionally exercise only the public surface that
``sdk/python/feral_sdk/__init__.py`` advertises: the package version,
the ``FeralClient`` HTTP+WS client, the ``FeralPlugin`` base class, the
``feral_tool`` decorator, and the ``SkillManifest`` builder.

The point is to fail loudly when the package import path changes,
when a top-level export goes missing, or when a constructor's required
arguments shift in a way that would break every downstream user.
Anything deeper (network round-trips, websockets) is out of scope here
and lives in dedicated integration tests.
"""

from __future__ import annotations

import inspect

import pytest


def test_package_imports() -> None:
    """The package must import cleanly with no required side effects."""
    import feral_sdk

    assert feral_sdk is not None


def test_version_is_non_empty_string() -> None:
    """``__version__`` is documented in the README as the canonical version."""
    import feral_sdk

    assert isinstance(feral_sdk.__version__, str)
    assert feral_sdk.__version__.strip() != ""
    # Reject the empty-PEP-440-placeholder shape so a forgotten release
    # bump does not pass the gate.
    assert feral_sdk.__version__ != "0.0.0"


def test_public_exports_resolve() -> None:
    """Every name in ``__all__`` must resolve to a real object."""
    import feral_sdk

    expected = {
        "FeralPlugin",
        "feral_tool",
        "FeralClient",
        "HUPDevice",
        "SkillManifest",
        "Endpoint",
        "Parameter",
        "GenUIComponent",
        "GenUICard",
        "GenUIMetric",
    }
    assert expected.issubset(set(feral_sdk.__all__))
    for name in expected:
        obj = getattr(feral_sdk, name, None)
        assert obj is not None, f"{name} declared in __all__ but missing"


def test_feral_client_instantiates_with_defaults() -> None:
    """The default constructor must not need any positional args."""
    from feral_sdk import FeralClient

    client = FeralClient()
    assert client.base_url, "FeralClient must expose base_url"
    assert client.base_url.startswith("http"), client.base_url
    # The ws_url is derived from base_url; it should already be wired up
    # at construction time — defer creation here would silently break
    # downstream code that reads ``client.ws_url`` before any call.
    assert client.ws_url.endswith("/v1/session"), client.ws_url


def test_feral_client_accepts_base_url() -> None:
    """The constructor must accept a custom brain URL."""
    from feral_sdk import FeralClient

    client = FeralClient("https://brain.example.com/")
    assert client.base_url == "https://brain.example.com"
    # ws_url must rewrite https → wss, not leave it as https://.
    assert client.ws_url.startswith("wss://"), client.ws_url


def test_feral_plugin_subclass_discovers_tools() -> None:
    """Decorating a method with @feral_tool should register it."""
    from feral_sdk import FeralPlugin, feral_tool

    class _Demo(FeralPlugin):
        name = "smoke"

        @feral_tool(description="Greet someone")
        async def greet(self, who: str) -> dict:
            return {"hello": who}

    plugin = _Demo()
    assert "greet" in plugin.tools
    manifest = plugin.to_manifest()
    assert manifest["skill_id"] == "smoke"
    endpoint_ids = [e["id"] for e in manifest["endpoints"]]
    assert "greet" in endpoint_ids


def test_skill_manifest_round_trip() -> None:
    """The dataclass-style manifest builder must serialise to dict cleanly."""
    from feral_sdk import Endpoint, Parameter, SkillManifest

    manifest = SkillManifest(
        skill_id="smoke_tool",
        description="Smoke test manifest",
        endpoints=[
            Endpoint(
                id="run",
                description="Run it",
                params=[Parameter(name="text", type="string", description="Input")],
            )
        ],
    )
    payload = manifest.to_dict() if hasattr(manifest, "to_dict") else None
    if payload is None:
        # Older shape: assert the dataclass holds the expected fields.
        assert manifest.skill_id == "smoke_tool"
        assert len(manifest.endpoints) == 1
    else:
        assert payload["skill_id"] == "smoke_tool"
        assert payload["endpoints"][0]["id"] == "run"


@pytest.mark.parametrize(
    "callable_name",
    ["health", "get_dashboard", "chat", "list_skills", "search_memory"],
)
def test_feral_client_methods_are_async(callable_name: str) -> None:
    """Every documented call on the client is an async coroutine fn."""
    from feral_sdk import FeralClient

    method = getattr(FeralClient, callable_name, None)
    assert method is not None, f"FeralClient.{callable_name} missing"
    assert inspect.iscoroutinefunction(method), (
        f"FeralClient.{callable_name} must be async; "
        "downstream code awaits it."
    )
