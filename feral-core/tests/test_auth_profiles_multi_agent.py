"""W16 — multi-agent auth profile isolation tests.

Two agent ids ("default" and "twin") hold disjoint OAuth tokens.
Cross-reads return ``None`` and deletions on one do not affect the
other. This is the openclaw "per-agent directory" guarantee from
``OPENCLAW_LESSONS.md`` §1.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def feral_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "feral"
    home.mkdir()
    monkeypatch.setenv("FERAL_HOME", str(home))
    return home


pytestmark = pytest.mark.no_auto_feral_home


def _seed_oauth(store, profile_id: str, refresh: str):
    from security.auth_profiles import OAuthCredential

    store.upsert(profile_id, OAuthCredential(
        provider="google",
        access=f"access-{profile_id}",
        refresh=refresh,
        expires=1700000000000,
    ))


def test_two_agents_have_disjoint_storage(feral_home: Path):
    from security.auth_profiles import AuthProfileFileStore, OAuthCredential

    default_store = AuthProfileFileStore("default")
    twin_store = AuthProfileFileStore("twin")

    _seed_oauth(default_store, "google:work", "refresh-default-work")
    _seed_oauth(twin_store, "google:personal", "refresh-twin-personal")

    assert default_store.list_profiles() == ["google:work"]
    assert twin_store.list_profiles() == ["google:personal"]

    cross_read_default = default_store.get("google:personal")
    cross_read_twin = twin_store.get("google:work")
    assert cross_read_default is None
    assert cross_read_twin is None

    own_default = default_store.get("google:work")
    own_twin = twin_store.get("google:personal")
    assert isinstance(own_default, OAuthCredential)
    assert isinstance(own_twin, OAuthCredential)
    assert own_default.refresh == "refresh-default-work"
    assert own_twin.refresh == "refresh-twin-personal"

    default_path = feral_home / "agents" / "default" / "auth_profiles.json"
    twin_path = feral_home / "agents" / "twin" / "auth_profiles.json"
    assert default_path.exists()
    assert twin_path.exists()
    assert default_path != twin_path


def test_deleting_one_agents_profile_does_not_affect_the_other(feral_home: Path):
    from security.auth_profiles import AuthProfileFileStore

    default_store = AuthProfileFileStore("default")
    twin_store = AuthProfileFileStore("twin")

    _seed_oauth(default_store, "shared-id", "refresh-default")
    _seed_oauth(twin_store, "shared-id", "refresh-twin")

    assert default_store.delete("shared-id") is True
    assert default_store.get("shared-id") is None

    surviving = twin_store.get("shared-id")
    assert surviving is not None
    assert surviving.refresh == "refresh-twin", (
        "twin's profile must survive default's delete"
    )


def test_invalid_agent_id_is_rejected(feral_home: Path):
    from security.auth_profiles import AuthProfileFileStore, validate_agent_id

    for bad in ("twin/..", "../escape", "with space", ""):
        with pytest.raises(ValueError):
            AuthProfileFileStore(bad)
        with pytest.raises(ValueError):
            validate_agent_id(bad)

    # ``None`` triggers the constructor default (DEFAULT_AGENT_ID); it
    # must NOT raise. The validator itself, however, refuses non-string
    # input outright so misuse from internal callers is loud.
    AuthProfileFileStore(None)
    with pytest.raises(ValueError):
        validate_agent_id(None)  # type: ignore[arg-type]


def test_usage_stats_persist_per_profile(feral_home: Path):
    from security.auth_profiles import (
        AuthProfileFileStore,
        ProfileUsageTracker,
    )

    store = AuthProfileFileStore("default")
    _seed_oauth(store, "google:work", "refresh-x")

    tracker = ProfileUsageTracker(store)
    tracker.record_success("google:work")
    tracker.record_success("google:work")
    tracker.record_failure("google:work", reason="auth")

    stats = tracker.stats("google:work")
    assert stats.success_count == 2
    assert stats.failure_count == 1
    assert stats.last_used_at is not None

    other = tracker.stats("never-used")
    assert other.success_count == 0
    assert other.failure_count == 0
    assert other.last_used_at is None
