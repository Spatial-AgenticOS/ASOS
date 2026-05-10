"""Audit-r8 brief #07 root-cause regression test.

Pin the contract that `BrainState.init` registers `self.provider_catalog`
as the process-wide `providers.catalog._SHARED` singleton BEFORE
`LLMProvider` is constructed. Without this wire, `_default_model_for`
falls through `get_shared_catalog()` which lazily creates an empty
`ProviderCatalog`, returns `""` for `default_model_for`, and the
failover path quietly leaves a non-chat model id in place — which
is how dated-transcribe ids leaked into chat completions despite a
clean settings.json + boot self-heal.

We don't boot the full brain here (that's an integration-grade ask).
Instead we assert the wiring contract: `set_shared_catalog` exists,
`get_shared_catalog` honours it, and `BrainState.init` source contains
the registration call (a static check that's robust to any future
refactor that splits `init` into helpers).
"""

from __future__ import annotations

import inspect

import pytest

from providers.catalog import (
    ProviderCatalog,
    get_shared_catalog,
    reset_shared_catalog,
    set_shared_catalog,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_shared_catalog()
    yield
    reset_shared_catalog()


def test_set_shared_catalog_replaces_singleton():
    custom = ProviderCatalog(cache_path=None)
    set_shared_catalog(custom)
    assert get_shared_catalog() is custom


def test_get_shared_catalog_lazy_builds_when_unset():
    # No registration → lazy build.
    first = get_shared_catalog()
    second = get_shared_catalog()
    assert first is second
    assert isinstance(first, ProviderCatalog)


def test_brainstate_init_registers_singleton_before_llmprovider():
    """Static guard: BrainState.init must call set_shared_catalog
    BEFORE constructing LLMProvider, otherwise `_default_model_for`
    consults a stale empty catalog and the leak returns."""
    from api.state import BrainState

    src = inspect.getsource(BrainState.init)
    set_pos = src.find("set_shared_catalog")
    llm_pos = src.find("LLMProvider(")
    assert set_pos != -1, (
        "BrainState.init must call providers.catalog.set_shared_catalog — "
        "see audit-r8 brief #07. Without this, the dated-transcribe "
        "model leak returns despite clean settings + classifier."
    )
    assert llm_pos != -1, (
        "BrainState.init no longer constructs LLMProvider — has the "
        "boot sequence changed? Verify the singleton registration "
        "still happens before any consumer of get_shared_catalog()."
    )
    assert set_pos < llm_pos, (
        "set_shared_catalog MUST run BEFORE LLMProvider() — otherwise "
        "the LLMProvider's `_default_model_for` will see a lazily-built "
        "empty catalog instead of the boot-time inventory."
    )
