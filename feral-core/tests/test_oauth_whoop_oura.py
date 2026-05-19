"""Tests for audit-r12 D9: Whoop + Oura are now first-class OAuth
providers + provider-registry coherence guard.

Pre-r12 ``integrations/health_platforms.py`` called
``OAuthManager.get_token("whoop")`` /
``get_token("oura")`` but neither id was registered in
``BUILTIN_PROVIDERS``. The call silently returned ``None`` and
``WhoopClient.connected`` / ``OuraClient.connected`` reported False
forever — the operator had no actionable signal that the
integration was broken.

This suite pins:

* both providers exist in ``BUILTIN_PROVIDERS`` with the live 2026
  endpoints + scopes (vendor docs cited in oauth_manager.py);
* env-var overrides flow through;
* ``build_authorize_url`` produces a PKCE-aware URL;
* the wider coherence invariant: every channel calling
  ``OAuthManager.get_token(<id>)`` has ``<id>`` registered. This is
  the "no more silent gaps" guard the audit asked for.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_feral_home(tmp_path, monkeypatch):
    """Empty FERAL home so user-side overrides in
    ``~/.feral/oauth_providers.json`` don't leak into the tests."""
    monkeypatch.setenv("FERAL_HOME", str(tmp_path))
    yield tmp_path


# ─────────────────────────────────────────────
# Whoop / Oura builtin entries
# ─────────────────────────────────────────────


def test_whoop_provider_is_builtin(isolated_feral_home):
    from integrations.oauth_manager import BUILTIN_PROVIDERS, OAuthManager

    assert "whoop" in BUILTIN_PROVIDERS
    cfg = BUILTIN_PROVIDERS["whoop"]
    assert cfg["auth_url"] == "https://api.prod.whoop.com/oauth/oauth2/auth"
    assert cfg["token_url"] == "https://api.prod.whoop.com/oauth/oauth2/token"
    assert cfg["pkce"] is True
    scopes = set(cfg["scopes"])
    # The ``offline`` scope is what unlocks refresh_token issuance per
    # the Whoop OAuth docs — without it the integration would die at
    # the 1h access-token expiry.
    assert "offline" in scopes
    assert "read:sleep" in scopes
    assert "read:recovery" in scopes
    assert "read:cycles" in scopes
    assert "read:workout" in scopes
    assert "read:body_measurement" in scopes
    mgr = OAuthManager()
    assert "whoop" in mgr._providers


def test_oura_provider_is_builtin(isolated_feral_home):
    from integrations.oauth_manager import BUILTIN_PROVIDERS, OAuthManager

    assert "oura" in BUILTIN_PROVIDERS
    cfg = BUILTIN_PROVIDERS["oura"]
    assert cfg["auth_url"] == "https://cloud.ouraring.com/oauth/authorize"
    assert cfg["token_url"] == "https://api.ouraring.com/oauth/token"
    assert cfg["pkce"] is True
    scopes = set(cfg["scopes"])
    # Surfaces the OuraClient queries in v2: daily summaries, heart
    # rate time series, workouts, sessions, tags.
    assert "daily" in scopes
    assert "heartrate" in scopes
    assert "workout" in scopes
    assert "session" in scopes
    assert "tag" in scopes
    mgr = OAuthManager()
    assert "oura" in mgr._providers


def test_env_vars_populate_whoop_client_id(isolated_feral_home, monkeypatch):
    monkeypatch.setenv("WHOOP_OAUTH_CLIENT_ID", "whoop-id")
    monkeypatch.setenv("WHOOP_OAUTH_CLIENT_SECRET", "whoop-secret")
    from integrations.oauth_manager import OAuthManager

    mgr = OAuthManager()
    provider = mgr._providers["whoop"]
    assert provider.client_id == "whoop-id"
    assert provider.client_secret == "whoop-secret"


def test_env_vars_populate_oura_client_id(isolated_feral_home, monkeypatch):
    monkeypatch.setenv("OURA_OAUTH_CLIENT_ID", "oura-id")
    monkeypatch.setenv("OURA_OAUTH_CLIENT_SECRET", "oura-secret")
    from integrations.oauth_manager import OAuthManager

    mgr = OAuthManager()
    provider = mgr._providers["oura"]
    assert provider.client_id == "oura-id"
    assert provider.client_secret == "oura-secret"


def test_build_authorize_url_for_whoop_includes_pkce(isolated_feral_home, monkeypatch):
    monkeypatch.setenv("WHOOP_OAUTH_CLIENT_ID", "w-id")
    from integrations.oauth_manager import OAuthManager

    mgr = OAuthManager()
    url = mgr.build_authorize_url("whoop")
    assert url is not None
    assert "api.prod.whoop.com/oauth/oauth2/auth" in url
    assert "client_id=w-id" in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    # ``offline`` MUST be in the requested scopes for refresh_token
    # issuance — otherwise the 1h Whoop access-token expiry would
    # silently kill the integration after an hour.
    assert "offline" in url


def test_build_authorize_url_for_oura_includes_pkce(isolated_feral_home, monkeypatch):
    monkeypatch.setenv("OURA_OAUTH_CLIENT_ID", "o-id")
    from integrations.oauth_manager import OAuthManager

    mgr = OAuthManager()
    url = mgr.build_authorize_url("oura")
    assert url is not None
    assert "cloud.ouraring.com/oauth/authorize" in url
    assert "client_id=o-id" in url
    assert "code_challenge=" in url


# ─────────────────────────────────────────────
# Coherence guard: every get_token("<id>") site MUST be registered.
# ─────────────────────────────────────────────


def _collect_get_token_ids(root: Path) -> set[str]:
    """Scan every Python file under ``root`` for static string
    arguments to ``get_token(...)`` and return the set of ids that
    appear. Uses :mod:`ast` so we don't get fooled by string-formatted
    fallbacks; only literal string ids are collected.
    """
    ids: set[str] = set()
    for py in root.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Match ``...get_token("foo")`` or
            # ``...get_token('foo', ...)`` — the manager's surface.
            fn = node.func
            attr_name = (
                fn.attr if isinstance(fn, ast.Attribute)
                else fn.id if isinstance(fn, ast.Name)
                else None
            )
            if attr_name != "get_token":
                continue
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                ids.add(first.value)
    return ids


def test_every_get_token_caller_has_registered_provider(isolated_feral_home):
    from integrations.oauth_manager import BUILTIN_PROVIDERS

    integrations_dir = ROOT / "integrations"
    callers = _collect_get_token_ids(integrations_dir)
    # Sanity: we found at least the four canonical health/workspace
    # integrations.
    expected_subset = {"whoop", "oura", "google", "microsoft"}
    assert expected_subset.issubset(callers), (
        f"static analysis missed expected get_token(...) call sites: "
        f"found={sorted(callers)}"
    )
    builtins = set(BUILTIN_PROVIDERS.keys())
    missing = callers - builtins
    assert not missing, (
        f"every channel calling OAuthManager.get_token(<id>) must have "
        f"<id> registered in BUILTIN_PROVIDERS — missing: {sorted(missing)}. "
        "Add the provider entry (with the live vendor endpoints + "
        "scopes) before merging."
    )
