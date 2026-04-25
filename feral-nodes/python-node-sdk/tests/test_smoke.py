"""Smoke tests for the public ``feral_node_sdk`` package.

These exercise only the public surface declared in
``feral-nodes/python-node-sdk/src/feral_node_sdk/__init__.py`` —
``FeralNode``, the ``capability`` enum module, the ``schemas`` module,
the pairing helpers, and ``discover_brain``. The point is to fail
loudly when the package import path drifts (it has been renamed at
least once historically), the public exports go missing, or the
``FeralNode`` constructor's required keyword arguments shift in a way
that would break every downstream daemon.

Note: the package's own ``FeralClient`` is intentionally NOT named —
this SDK exposes ``FeralNode`` (the HUP-v1 client). The smoke shape
asked for in the W10 brief assumed ``FeralClient``; we exercise
``FeralNode`` instead because that is the actual public surface, per
``__init__.py``.
"""

from __future__ import annotations

from pathlib import Path
import sys

# `conftest.py` injects the SDK src/ onto sys.path, but during local
# `python -m pytest tests/` the conftest is loaded *after* the test
# imports; defensively wire src/ here too so this file works in
# isolation (e.g. `pytest tests/test_smoke.py`).
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_package_imports() -> None:
    """The package must import cleanly with no required side effects."""
    import feral_node_sdk

    assert feral_node_sdk is not None


def test_version_is_non_empty_string() -> None:
    """``__version__`` is the canonical version string for the SDK."""
    import feral_node_sdk

    assert isinstance(feral_node_sdk.__version__, str)
    assert feral_node_sdk.__version__.strip() != ""
    assert feral_node_sdk.__version__ != "0.0.0"


def test_hup_version_is_non_empty_string() -> None:
    """``HUP_VERSION`` pins the wire-protocol version the SDK speaks."""
    import feral_node_sdk

    assert isinstance(feral_node_sdk.HUP_VERSION, str)
    assert feral_node_sdk.HUP_VERSION.strip() != ""


def test_public_exports_resolve() -> None:
    """Every name in ``__all__`` must resolve to a real object."""
    import feral_node_sdk

    expected = {
        "FeralNode",
        "capability",
        "schemas",
        "load_key",
        "save_key",
        "discover_brain",
    }
    assert expected.issubset(set(feral_node_sdk.__all__))
    for name in expected:
        obj = getattr(feral_node_sdk, name, None)
        assert obj is not None, f"{name} declared in __all__ but missing"


def test_feral_node_instantiates_with_minimum_kwargs() -> None:
    """The constructor must accept the documented minimum kwargs."""
    from feral_node_sdk import FeralNode

    node = FeralNode(node_id="smoke-test-node", name="smoke")
    assert node.node_id == "smoke-test-node"
    assert node.name == "smoke"
    # `capabilities` defaults to () — the resolved list must be an empty
    # list, not None, so downstream `for cap in node.capabilities` loops
    # never crash.
    assert node.capabilities == []
    # The action-handler registry exists at construction time.
    assert hasattr(node, "_action_handlers")


def test_feral_node_capabilities_normalize() -> None:
    """Mixed Capability + str inputs must coerce to a list[str]."""
    from feral_node_sdk import FeralNode, capability

    node = FeralNode(
        node_id="smoke-cap",
        capabilities=[capability.Capability.HEART_RATE, "buzzer"],
    )
    assert "heart_rate" in node.capabilities
    assert "buzzer" in node.capabilities
    # `sensors` and `actuators` get auto-derived from capabilities when
    # the caller does not pass them explicitly. heart_rate → sensor,
    # buzzer → actuator.
    assert "heart_rate" in node.sensors
    assert "buzzer" in node.actuators


def test_on_action_decorator_registers_handler() -> None:
    """`@node.on_action("name")` registers an async handler."""
    from feral_node_sdk import FeralNode

    node = FeralNode(node_id="smoke-handler")

    @node.on_action("buzz")
    async def _buzz(params: dict) -> dict:
        return {"ok": True, "params": params}

    assert "buzz" in node._action_handlers
    # Calling the registered handler must return the awaited value
    # without raising — exercises the wrapper trivially.
    import asyncio

    result = asyncio.run(node._action_handlers["buzz"]({"x": 1}))
    assert result == {"ok": True, "params": {"x": 1}}


def test_capability_enum_has_documented_values() -> None:
    """The capability module exposes the documented top-level enum."""
    from feral_node_sdk import capability

    assert hasattr(capability, "Capability")
    # A handful of well-known capabilities every wristband / glasses
    # daemon uses today; if these go missing, every existing example
    # breaks.
    members = {m.name for m in capability.Capability}
    for required in ("HEART_RATE", "BATTERY", "BUZZER"):
        assert required in members, f"{required} missing from Capability"


def test_schemas_module_exports_build_frame() -> None:
    """`schemas.build_frame` is the wire-frame helper the node uses."""
    from feral_node_sdk import schemas

    assert callable(getattr(schemas, "build_frame", None))
    assert isinstance(schemas.HUP_VERSION, str)
