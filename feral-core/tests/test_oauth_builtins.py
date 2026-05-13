"""
PR 11: Google + Microsoft are now first-class OAuth providers.

Before this PR, ``integrations/google_drive.py`` /
``google_contacts.py`` / ``email.py`` (Gmail) / ``calendar.py`` /
``microsoft365.py`` all called ``OAuthManager.get_token("google")``
or ``get_token("microsoft")``, but neither provider id existed in
``BUILTIN_PROVIDERS``. The result was a silent "no token" return
that no operator could remediate without writing
``~/.feral/oauth_providers.json`` by hand.

These tests pin the new wiring:

* Both providers are present in ``BUILTIN_PROVIDERS`` with the right
  metadata for the integrations that call them.
* Scope lists cover the actual API surfaces the integrations hit
  (Gmail send + Calendar write + Drive + People + Graph mail/files).
* Authorize URL building works without a custom config file.
* Env-var overrides (``GOOGLE_OAUTH_CLIENT_ID`` /
  ``MICROSOFT_OAUTH_CLIENT_ID``) populate ``client_id`` at boot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_feral_home(tmp_path, monkeypatch):
    """Point ``OAuthManager`` at an empty FERAL home so user-side
    overrides in ``~/.feral/oauth_providers.json`` don't leak into the
    tests."""
    monkeypatch.setenv("FERAL_HOME", str(tmp_path))
    yield tmp_path


def test_google_provider_is_builtin(isolated_feral_home):
    from integrations.oauth_manager import BUILTIN_PROVIDERS, OAuthManager

    assert "google" in BUILTIN_PROVIDERS
    google = BUILTIN_PROVIDERS["google"]
    assert google["auth_url"].startswith("https://accounts.google.com/")
    assert google["token_url"].startswith("https://oauth2.googleapis.com/")
    assert google["pkce"] is True
    # Scopes cover what the integrations actually call.
    scopes = set(google["scopes"])
    assert "https://www.googleapis.com/auth/gmail.send" in scopes
    assert "https://www.googleapis.com/auth/drive" in scopes
    assert "https://www.googleapis.com/auth/contacts.readonly" in scopes
    assert "https://www.googleapis.com/auth/calendar" in scopes

    mgr = OAuthManager()
    assert "google" in mgr._providers


def test_microsoft_provider_is_builtin(isolated_feral_home):
    from integrations.oauth_manager import BUILTIN_PROVIDERS, OAuthManager

    assert "microsoft" in BUILTIN_PROVIDERS
    ms = BUILTIN_PROVIDERS["microsoft"]
    assert "login.microsoftonline.com" in ms["auth_url"]
    assert ms["pkce"] is True
    scopes = set(ms["scopes"])
    assert "Mail.Send" in scopes
    assert "Calendars.ReadWrite" in scopes
    assert "Files.ReadWrite" in scopes
    assert "offline_access" in scopes  # refresh tokens

    mgr = OAuthManager()
    assert "microsoft" in mgr._providers


def test_env_vars_populate_google_client_id(isolated_feral_home, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-google-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-google-secret")
    from integrations.oauth_manager import OAuthManager

    mgr = OAuthManager()
    provider = mgr._providers["google"]
    assert provider.client_id == "test-google-id"
    assert provider.client_secret == "test-google-secret"


def test_env_vars_populate_microsoft_client_id(isolated_feral_home, monkeypatch):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "test-ms-id")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "test-ms-secret")
    from integrations.oauth_manager import OAuthManager

    mgr = OAuthManager()
    provider = mgr._providers["microsoft"]
    assert provider.client_id == "test-ms-id"
    assert provider.client_secret == "test-ms-secret"


def test_build_authorize_url_for_google(isolated_feral_home, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "abc-id")
    from integrations.oauth_manager import OAuthManager

    mgr = OAuthManager()
    url = mgr.build_authorize_url("google")
    assert url is not None
    assert "accounts.google.com" in url
    assert "client_id=abc-id" in url
    assert "scope=" in url
    # PKCE must produce both the challenge and code_challenge_method.
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url


def test_build_authorize_url_for_microsoft(isolated_feral_home, monkeypatch):
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "ms-id")
    from integrations.oauth_manager import OAuthManager

    mgr = OAuthManager()
    url = mgr.build_authorize_url("microsoft")
    assert url is not None
    assert "login.microsoftonline.com" in url
    assert "client_id=ms-id" in url
    assert "code_challenge=" in url  # PKCE on for Microsoft too


def test_list_providers_advertises_google_and_microsoft(isolated_feral_home, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "g-id")
    from integrations.oauth_manager import OAuthManager

    mgr = OAuthManager()
    listing = mgr.list_providers()
    ids = {p["id"] for p in listing}
    assert "google" in ids
    assert "microsoft" in ids
    google_row = next(p for p in listing if p["id"] == "google")
    # The list surface honestly reports whether a client id is wired,
    # so the UI can label stubs vs ready-to-connect.
    assert google_row["has_client_id"] is True
    ms_row = next(p for p in listing if p["id"] == "microsoft")
    assert ms_row["has_client_id"] is False
