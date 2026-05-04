"""Tests for ``cli.publish.registry_base_urls`` and the v2026.5.13
fallback list it powers.

Real-user feedback on v2026.5.12: the marketplace surfaced
``registry unreachable: [Errno 8] nodename nor servname provided`` on
networks that couldn't resolve our IPv6-only ``registry.feral.sh``.
The fix is a single resolver that returns the primary URL plus
fallback URL(s) (e.g. the Fly app URL which has both A and AAAA
records). This module pins the resolver's contract so the marketplace
and AppRegistry stay aligned.
"""

from __future__ import annotations

import pytest

from cli.publish import (
    DEFAULT_REGISTRY_FALLBACK_URLS,
    DEFAULT_REGISTRY_URL,
    registry_base_url,
    registry_base_urls,
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FERAL_REGISTRY_URL", raising=False)
    monkeypatch.delenv("FERAL_REGISTRY_FALLBACK_URLS", raising=False)
    monkeypatch.setenv("FERAL_HOME", "/tmp/feral-test-home-does-not-exist")


def test_default_returns_primary_then_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    bases = registry_base_urls()
    assert bases[0] == DEFAULT_REGISTRY_URL
    for fb in DEFAULT_REGISTRY_FALLBACK_URLS:
        assert fb in bases, "default fallback list must be appended"
    assert len(bases) == 1 + len(DEFAULT_REGISTRY_FALLBACK_URLS)


def test_legacy_helper_returns_primary_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    # `registry_base_url()` is the back-compat single-URL helper.
    assert registry_base_url() == DEFAULT_REGISTRY_URL


def test_explicit_override_drops_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom registry pointers do NOT auto-fall-back to feral.sh.

    Operators running their own registry should not see traffic
    silently leak to feral.sh's Fly app on a connect failure.
    """
    _clear_env(monkeypatch)
    bases = registry_base_urls(cli_override="https://my-self-hosted-registry.example/")
    assert bases == ["https://my-self-hosted-registry.example"]


def test_env_override_drops_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("FERAL_REGISTRY_URL", "https://staging.example.com/")
    bases = registry_base_urls()
    assert bases == ["https://staging.example.com"]


def test_env_fallback_list_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(
        "FERAL_REGISTRY_FALLBACK_URLS",
        "https://a.example.com/, https://b.example.com",
    )
    bases = registry_base_urls()
    assert bases[0] == DEFAULT_REGISTRY_URL  # primary unchanged
    assert "https://a.example.com" in bases
    assert "https://b.example.com" in bases
    # Default canonical fallback should NOT also be appended once an
    # explicit list is supplied -- otherwise the override is meaningless.
    assert "https://feral-registry.fly.dev" not in bases


def test_no_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("FERAL_REGISTRY_URL", DEFAULT_REGISTRY_URL)
    monkeypatch.setenv("FERAL_REGISTRY_FALLBACK_URLS", DEFAULT_REGISTRY_URL)
    bases = registry_base_urls()
    # primary + fallback both set to the same URL must collapse to 1.
    assert bases == [DEFAULT_REGISTRY_URL]


def test_trailing_slashes_are_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    bases = registry_base_urls(cli_override="https://example.com/path/")
    assert bases == ["https://example.com/path"]
