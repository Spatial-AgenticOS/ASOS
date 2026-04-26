"""W16 — legacy ``credentials.json`` → per-agent migration tests.

Seeds a flat pre-W9 layout under ``$FERAL_HOME/credentials.json`` with
one OAuth blob and two API keys. After running the migration we
assert:

* the per-agent file ``$FERAL_HOME/agents/default/auth_profiles.json``
  exists, mode 0600;
* every entry round-trips through the credential-from-dict reader at
  the right shape;
* the legacy file is backed up to ``credentials.json.bak.legacy.w16``
  at mode 0600;
* the original legacy file is **not** deleted (W9 owns that lifecycle);
* a second migrate call is a no-op (idempotence).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

# Module owns FERAL_HOME so the autouse isolation fixture doesn't
# clobber the legacy file we seed under it.
pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture
def feral_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "feral"
    home.mkdir()
    monkeypatch.setenv("FERAL_HOME", str(home))
    return home


def _seed_legacy(feral_home: Path) -> Path:
    legacy = feral_home / "credentials.json"
    legacy.write_text(json.dumps({
        "openai_api_key": "sk-test-openai-do-not-commit",
        "anthropic_api_key": "sk-ant-test-do-not-commit",
        "google_oauth": {
            "provider": "google",
            "access_token": "ya29.test-access",
            "refresh_token": "1//test-refresh",
            "expires": 1700000000000,
            "client_id": "test-client.apps.googleusercontent.com",
            "email": "tester@example.com",
        },
    }, indent=2))
    if os.name == "posix":
        os.chmod(legacy, 0o600)
    return legacy


def test_migration_writes_per_agent_file_with_correct_shapes(feral_home: Path):
    from security.auth_profiles import (
        AuthProfileFileStore,
        ApiKeyCredential,
        OAuthCredential,
        run_migration_if_needed,
    )

    legacy = _seed_legacy(feral_home)
    result = run_migration_if_needed()

    assert result.migrated is True
    assert result.entries == 3
    assert result.api_keys == 2
    assert result.oauth == 1

    destination = feral_home / "agents" / "default" / "auth_profiles.json"
    assert destination.exists(), f"per-agent file missing: {destination}"
    assert result.destination == destination

    if os.name == "posix":
        mode = stat.S_IMODE(destination.stat().st_mode)
        assert mode == 0o600, f"per-agent file mode: 0o{mode:o}"

    store = AuthProfileFileStore("default")
    profiles = store.load()
    assert set(profiles.keys()) == {"openai_api_key", "anthropic_api_key", "google_oauth"}

    openai_cred = profiles["openai_api_key"]
    assert isinstance(openai_cred, ApiKeyCredential)
    assert openai_cred.provider == "openai"
    assert openai_cred.key == "sk-test-openai-do-not-commit"

    anthropic_cred = profiles["anthropic_api_key"]
    assert isinstance(anthropic_cred, ApiKeyCredential)
    assert anthropic_cred.provider == "anthropic"

    google_cred = profiles["google_oauth"]
    assert isinstance(google_cred, OAuthCredential)
    assert google_cred.provider == "google"
    assert google_cred.refresh == "1//test-refresh"
    assert google_cred.access == "ya29.test-access"
    assert google_cred.expires == 1700000000000
    assert google_cred.email == "tester@example.com"

    assert legacy.exists(), "W9 owns the legacy file lifecycle; W16 must NOT delete it"


def test_migration_creates_backup_at_mode_0600(feral_home: Path):
    from security.auth_profiles import LEGACY_BACKUP_SUFFIX, run_migration_if_needed

    legacy = _seed_legacy(feral_home)
    result = run_migration_if_needed()

    expected_backup = legacy.with_name(legacy.name + LEGACY_BACKUP_SUFFIX)
    assert result.backup_path == expected_backup
    assert expected_backup.exists()

    assert expected_backup.read_bytes() == legacy.read_bytes(), (
        "backup must be a byte-for-byte copy of the legacy file"
    )

    if os.name == "posix":
        mode = stat.S_IMODE(expected_backup.stat().st_mode)
        assert mode == 0o600, f"backup mode: 0o{mode:o}"


def test_migration_is_idempotent_on_second_run(feral_home: Path):
    from security.auth_profiles import run_migration_if_needed

    _seed_legacy(feral_home)
    first = run_migration_if_needed()
    assert first.migrated is True

    second = run_migration_if_needed()
    assert second.migrated is False
    assert second.noop_reason == "already-migrated"
    assert second.backup_path is None
    assert second.entries == 0


def test_migration_noop_when_no_legacy_file(feral_home: Path):
    from security.auth_profiles import run_migration_if_needed

    result = run_migration_if_needed()
    assert result.migrated is False
    assert result.noop_reason == "no-legacy-file"


def test_migration_rejects_malformed_legacy_value(feral_home: Path):
    from security.auth_profiles import run_migration_if_needed

    legacy = feral_home / "credentials.json"
    legacy.write_text(json.dumps({
        "weird_thing": ["not", "supported"],
    }))

    with pytest.raises(ValueError, match="weird_thing"):
        run_migration_if_needed()
