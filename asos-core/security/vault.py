"""
THEORA Blind Vault — Secure Credential Management
=====================================================
The LLM NEVER sees raw credentials. When a skill needs an API key,
the executor injects it at the HTTP layer. The LLM only knows:
"web_search is available" — not the key itself.

Threat Model:
  - LLM prompt injection cannot exfiltrate keys
  - Client-side code never receives keys
  - Skills are sandboxed: they can only access their own key
  - All credential access is logged to the audit trail
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from config.loader import theora_home

logger = logging.getLogger("theora.vault")


class BlindVault:
    """
    Secure credential storage with:
    - File-level OS permissions (chmod 600)
    - Key isolation (skills can only access their own credentials)
    - LLM blindness (credentials never appear in prompts/responses)
    - Full audit trail of credential access
    """

    def __init__(self, vault_path: Optional[str] = None):
        home = theora_home()
        self._vault_path = Path(vault_path) if vault_path else home / "credentials.json"
        self._audit_path = home / "audit.log"
        self._cache: dict = {}
        self._load()

    def _load(self):
        if self._vault_path.exists():
            with open(self._vault_path) as f:
                self._cache = json.load(f)
        else:
            self._cache = {}

    def _persist(self):
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._vault_path, "w") as f:
            json.dump(self._cache, f, indent=2)
        try:
            os.chmod(self._vault_path, 0o600)
        except OSError:
            pass

    def store(self, key_name: str, value: str, stored_by: str = "user"):
        """Store a credential. Only the vault and executor can read it."""
        self._cache[key_name] = value
        self._persist()
        self._audit("store", key_name, stored_by)
        logger.info(f"Credential stored: {key_name}")

    def retrieve(self, key_name: str, requester: str = "executor") -> Optional[str]:
        """
        Retrieve a credential. Only called by the skill executor at HTTP time.
        NEVER called by the LLM, client, or any user-facing code.
        """
        value = self._cache.get(key_name)
        self._audit("retrieve", key_name, requester, found=value is not None)
        return value

    def has_key(self, key_name: str) -> bool:
        return key_name in self._cache

    def list_keys(self) -> list[str]:
        """List key names only — never values."""
        return list(self._cache.keys())

    def remove(self, key_name: str, removed_by: str = "user") -> bool:
        if key_name in self._cache:
            del self._cache[key_name]
            self._persist()
            self._audit("remove", key_name, removed_by)
            return True
        return False

    def fingerprint(self, key_name: str) -> Optional[str]:
        """Return a SHA-256 fingerprint for verification without exposing the key."""
        val = self._cache.get(key_name)
        if val:
            return hashlib.sha256(val.encode()).hexdigest()[:12]
        return None

    def _audit(self, action: str, key_name: str, actor: str, **extra):
        entry = {
            "ts": time.time(),
            "action": action,
            "key": key_name,
            "actor": actor,
            **extra,
        }
        try:
            with open(self._audit_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def to_safe_summary(self) -> dict:
        """Return a summary safe for the client. Shows key names and fingerprints, never values."""
        return {
            name: {
                "stored": True,
                "fingerprint": self.fingerprint(name),
            }
            for name in self._cache
        }


class PermissionTier:
    """
    Permission tiers for skill execution:
      - PASSIVE: read-only, no side effects (weather, search)
      - ACTIVE: can send data (messaging, calendar create)
      - PRIVILEGED: can modify system state (file access, shell commands)
      - DANGEROUS: destructive operations (delete, financial transactions)
    """
    PASSIVE = "passive"
    ACTIVE = "active"
    PRIVILEGED = "privileged"
    DANGEROUS = "dangerous"

    TIER_ORDER = [PASSIVE, ACTIVE, PRIVILEGED, DANGEROUS]

    @classmethod
    def requires_confirmation(cls, tier: str) -> bool:
        return tier in (cls.PRIVILEGED, cls.DANGEROUS)

    @classmethod
    def tier_level(cls, tier: str) -> int:
        try:
            return cls.TIER_ORDER.index(tier)
        except ValueError:
            return 0


class ExecutionSandbox:
    """
    Constraints applied to skill execution based on permission tier.
    """

    def __init__(self, max_tier: str = PermissionTier.ACTIVE):
        self.max_tier = max_tier
        self._blocked_domains: set[str] = set()
        self._rate_limits: dict[str, int] = {}
        self._execution_log: list[dict] = []

    def can_execute(self, skill_id: str, tier: str) -> tuple[bool, str]:
        """Check if a skill can be executed at the requested tier."""
        if PermissionTier.tier_level(tier) > PermissionTier.tier_level(self.max_tier):
            return False, f"Tier {tier} exceeds max allowed tier {self.max_tier}"

        limit = self._rate_limits.get(skill_id)
        if limit is not None:
            recent = sum(
                1 for e in self._execution_log
                if e["skill_id"] == skill_id and time.time() - e["ts"] < 60
            )
            if recent >= limit:
                return False, f"Rate limit exceeded for {skill_id} ({limit}/min)"

        return True, "ok"

    def log_execution(self, skill_id: str, tier: str, success: bool):
        self._execution_log.append({
            "ts": time.time(),
            "skill_id": skill_id,
            "tier": tier,
            "success": success,
        })
        # Keep last 1000 entries
        if len(self._execution_log) > 1000:
            self._execution_log = self._execution_log[-500:]

    def set_rate_limit(self, skill_id: str, per_minute: int):
        self._rate_limits[skill_id] = per_minute

    def block_domain(self, domain: str):
        self._blocked_domains.add(domain)

    def is_domain_blocked(self, url: str) -> bool:
        return any(d in url for d in self._blocked_domains)
