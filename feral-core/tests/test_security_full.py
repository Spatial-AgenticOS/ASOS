"""
Tests for blind vault, permission tiers, sandbox policy, and execution sandbox.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from security.sandbox_policy import SandboxPolicy
from security.vault import BlindVault, ExecutionSandbox, PermissionTier


@pytest.fixture
def vault_path(tmp_path: Path) -> Path:
    return tmp_path / "credentials.json"


@pytest.fixture
def blind_vault(vault_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BlindVault:
    monkeypatch.setenv("FERAL_HOME", str(tmp_path / "feral"))
    return BlindVault(vault_path=str(vault_path))


class TestBlindVault:
    """``BlindVault`` store/retrieve/list and rotation via remove + store."""

    def test_store_retrieve_list_keys(self, blind_vault: BlindVault) -> None:
        blind_vault.store("svc_a", "secret-one", stored_by="test")
        blind_vault.store("svc_b", "secret-two", stored_by="test")

        assert blind_vault.retrieve("svc_a") == "secret-one"
        assert blind_vault.retrieve("svc_b") == "secret-two"
        keys = sorted(blind_vault.list_keys())
        assert keys == ["svc_a", "svc_b"]

    def test_key_rotation(self, blind_vault: BlindVault) -> None:
        blind_vault.store("rotating", "v1")
        assert blind_vault.retrieve("rotating") == "v1"
        blind_vault.remove("rotating", removed_by="test")
        assert blind_vault.retrieve("rotating") is None
        blind_vault.store("rotating", "v2")
        assert blind_vault.retrieve("rotating") == "v2"


class TestPermissionTier:
    """
    Execution tiers for sandboxing. Skill manifests may use strings like SAFE/WARN;
    ``PermissionTier`` uses passive → dangerous progression.
    """

    def test_tier_constants_exist(self) -> None:
        assert PermissionTier.PASSIVE == "passive"
        assert PermissionTier.ACTIVE == "active"
        assert PermissionTier.PRIVILEGED == "privileged"
        assert PermissionTier.DANGEROUS == "dangerous"

    def test_tier_ordering_and_confirmation(self) -> None:
        assert PermissionTier.tier_level(PermissionTier.DANGEROUS) > PermissionTier.tier_level(
            PermissionTier.ACTIVE
        )
        assert PermissionTier.requires_confirmation(PermissionTier.PASSIVE) is False
        assert PermissionTier.requires_confirmation(PermissionTier.DANGEROUS) is True


class TestSandboxPolicy:
    def test_load_defaults(self) -> None:
        p = SandboxPolicy()
        d = p.to_dict()
        assert d["version"] == "1.0"
        assert "network" in d
        assert "filesystem" in d

    def test_allowed_domains_allowlist(self) -> None:
        p = SandboxPolicy()
        assert p.can_access_domain("api.tavily.com") is True
        assert p.can_access_domain("malicious.example.com") is False

    def test_blocked_paths_in_default_policy(self) -> None:
        p = SandboxPolicy()
        blocked = p.to_dict().get("filesystem", {}).get("blocked_paths", [])
        assert any(".ssh" in str(x) for x in blocked)


class TestExecutionSandbox:
    def test_rate_limit_blocks_repeated_execution(self) -> None:
        box = ExecutionSandbox(max_tier=PermissionTier.DANGEROUS)
        box.set_rate_limit("heavy_skill", per_minute=1)

        ok1, msg1 = box.can_execute("heavy_skill", PermissionTier.ACTIVE)
        assert ok1 is True
        box.log_execution("heavy_skill", PermissionTier.ACTIVE, success=True)

        ok2, msg2 = box.can_execute("heavy_skill", PermissionTier.ACTIVE)
        assert ok2 is False
        assert "Rate limit" in msg2

    def test_tier_enforcement(self) -> None:
        box = ExecutionSandbox(max_tier=PermissionTier.ACTIVE)
        ok, msg = box.can_execute("x", PermissionTier.DANGEROUS)
        assert ok is False
        assert "exceeds" in msg.lower() or "tier" in msg.lower()
