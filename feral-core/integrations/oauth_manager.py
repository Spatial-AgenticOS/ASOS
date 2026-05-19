"""
FERAL OAuth Manager — Secure Token Lifecycle
===============================================
Manages OAuth2 flows (Authorization Code + PKCE) and long-lived
API tokens.  All tokens are stored in the BlindVault — encrypted,
audited, and never exposed to the LLM.

Supports:
  - OAuth2 Authorization Code with PKCE (Spotify, Notion)
  - Long-lived API tokens (Home Assistant, Philips Hue)
  - Automatic token refresh via refresh_token
"""

from __future__ import annotations
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import httpx

from config.loader import feral_home
from config.runtime import brain_public_base_url

logger = logging.getLogger("feral.oauth")

OAUTH_CONFIG_PATH = feral_home() / "oauth_providers.json"
OAUTH_STATE_PATH = feral_home() / "oauth_state.json"


def _default_redirect_uri() -> str:
    return f"{brain_public_base_url()}/api/oauth/callback"


class OAuthProvider:
    """Configuration for a single OAuth2 provider."""

    def __init__(self, data: dict):
        self.id: str = data.get("id", "")
        self.name: str = data.get("name", "")
        self.auth_url: str = data.get("auth_url", "")
        self.token_url: str = data.get("token_url", "")
        self.client_id: str = data.get("client_id", "")
        self.client_secret: str = data.get("client_secret", "")
        self.scopes: list[str] = data.get("scopes", [])
        self.redirect_uri: str = data.get("redirect_uri", _default_redirect_uri())
        self.pkce: bool = data.get("pkce", True)
        self.auth_type: str = data.get("auth_type", "oauth2")


BUILTIN_PROVIDERS = {
    "spotify": {
        "id": "spotify",
        "name": "Spotify",
        "auth_url": "https://accounts.spotify.com/authorize",
        "token_url": "https://accounts.spotify.com/api/token",
        "client_id": "",
        "scopes": [
            "user-read-playback-state",
            "user-modify-playback-state",
            "user-read-currently-playing",
            "playlist-read-private",
            "user-library-read",
        ],
        "pkce": True,
        "auth_type": "oauth2",
    },
    "notion": {
        "id": "notion",
        "name": "Notion",
        "auth_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "client_id": "",
        "scopes": [],
        "pkce": False,
        "auth_type": "oauth2",
    },
    "home_assistant": {
        "id": "home_assistant",
        "name": "Home Assistant",
        "auth_type": "token",
    },
    # ──────────────────────────────────────────────────────────────────
    # PR 11: Google + Microsoft built-ins.
    #
    # ``integrations/google_drive.py``, ``google_contacts.py``,
    # ``email.py`` (Gmail), ``calendar.py``, and ``microsoft365.py``
    # all call ``OAuthManager.get_token("google")`` or
    # ``get_token("microsoft")``. Until now those provider ids were
    # absent from ``BUILTIN_PROVIDERS``, so unless the operator
    # hand-rolled ``~/.feral/oauth_providers.json`` the integrations
    # silently had no token. The truthfulness mission says: fail
    # honestly with a real OAuth URL instead of returning a token that
    # was never going to exist.
    #
    # Scopes are the *intersection* of what the integrations actually
    # call (People API contact reads, Drive metadata + files, Gmail
    # read+modify, Calendar read+write, Graph user/files/mail). PKCE
    # is enabled where the provider supports it for installed-app
    # security.
    "google": {
        "id": "google",
        "name": "Google",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "client_id": "",
        "scopes": [
            # Identity for the connected account.
            "openid",
            "email",
            "profile",
            # Gmail: read + send + modify labels (matches
            # integrations/email.py call sites).
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
            # Drive: read + write metadata + file content for
            # integrations/google_drive.py.
            "https://www.googleapis.com/auth/drive",
            # Contacts (People API): read directory + connections.
            "https://www.googleapis.com/auth/contacts.readonly",
            # Calendar: read + write events.
            "https://www.googleapis.com/auth/calendar",
        ],
        "pkce": True,
        "auth_type": "oauth2",
    },
    "microsoft": {
        "id": "microsoft",
        "name": "Microsoft",
        # The "common" tenant accepts both personal and work accounts;
        # operators with single-tenant apps can override via
        # ~/.feral/oauth_providers.json.
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "client_id": "",
        "scopes": [
            # Graph identity / refresh.
            "openid",
            "email",
            "profile",
            "offline_access",
            # Calendar/Mail/Files surfaces used by microsoft365.py.
            "User.Read",
            "Mail.Read",
            "Mail.Send",
            "Calendars.ReadWrite",
            "Files.ReadWrite",
            "Contacts.Read",
        ],
        "pkce": True,
        "auth_type": "oauth2",
    },
    # ──────────────────────────────────────────────────────────────────
    # audit-r12 D9: Whoop + Oura built-ins.
    #
    # ``integrations/health_platforms.py`` calls
    # ``OAuthManager.get_token("whoop")`` /
    # ``get_token("oura")`` but neither id was registered, so the
    # call returned ``None`` and ``WhoopClient.connected`` /
    # ``OuraClient.connected`` were silently False forever. Same
    # silent-degrade pattern as the Google/Microsoft gap PR 11
    # closed; this entry registers the two so the health platforms
    # actually authenticate.
    #
    # Endpoints + scopes verified against the live vendor docs on
    # 2026-05-19 — do not regress these without re-verifying:
    #
    # Whoop:
    #   https://developer.whoop.com/docs/developing/oauth
    #   - Auth URL: https://api.prod.whoop.com/oauth/oauth2/auth
    #   - Token URL: https://api.prod.whoop.com/oauth/oauth2/token
    #   - Access tokens ~1h; refresh tokens require ``offline`` scope.
    #
    # Oura (Cloud API v2):
    #   https://cloud.ouraring.com/v2/docs
    #   - Auth URL: https://cloud.ouraring.com/oauth/authorize
    #   - Token URL: https://api.ouraring.com/oauth/token
    #   - Access tokens long-lived; refresh tokens issued under the
    #     ``offline_access`` scope.
    "whoop": {
        "id": "whoop",
        "name": "Whoop",
        "auth_url": "https://api.prod.whoop.com/oauth/oauth2/auth",
        "token_url": "https://api.prod.whoop.com/oauth/oauth2/token",
        "client_id": "",
        "scopes": [
            # MUST include ``offline`` to receive a refresh_token per
            # the Whoop OAuth docs (Receiving a Refresh Token).
            "offline",
            # Match the surfaces ``WhoopClient`` actually queries:
            # recovery, sleep, cycles, workouts, body_measurement, and
            # profile (for the connected member's id).
            "read:recovery",
            "read:sleep",
            "read:cycles",
            "read:workout",
            "read:body_measurement",
            "read:profile",
        ],
        "pkce": True,
        "auth_type": "oauth2",
    },
    "oura": {
        "id": "oura",
        "name": "Oura Ring",
        "auth_url": "https://cloud.ouraring.com/oauth/authorize",
        "token_url": "https://api.ouraring.com/oauth/token",
        "client_id": "",
        "scopes": [
            "email",
            "personal",
            # Match the v2 endpoints ``OuraClient`` queries:
            # ``daily_sleep``, ``daily_readiness``, ``daily_activity``,
            # and the heartrate time series.
            "daily",
            "heartrate",
            "workout",
            "session",
            "tag",
        ],
        "pkce": True,
        "auth_type": "oauth2",
    },
}


class OAuthManager:
    """
    Manages the full OAuth2 lifecycle and token storage.
    Tokens are persisted in the BlindVault (or a local JSON fallback).
    """

    def __init__(self, vault=None):
        self._vault = vault
        self._providers: dict[str, OAuthProvider] = {}
        self._pending_states: dict[str, dict] = {}
        self._tokens: dict[str, dict] = {}
        self._http = httpx.AsyncClient(timeout=15.0)
        self._load_providers()
        self._load_tokens()

    def _load_providers(self):
        """Load provider configs from disk, merge with builtins."""
        for pid, pdata in BUILTIN_PROVIDERS.items():
            self._providers[pid] = OAuthProvider(pdata)

        if OAUTH_CONFIG_PATH.exists():
            try:
                custom = json.loads(OAUTH_CONFIG_PATH.read_text())
                for pid, pdata in custom.items():
                    merged = BUILTIN_PROVIDERS.get(pid, {}).copy()
                    merged.update(pdata)
                    self._providers[pid] = OAuthProvider(merged)
            except Exception as e:
                logger.warning(f"Failed to load custom OAuth providers: {e}")

        env_spotify_id = os.getenv("SPOTIFY_CLIENT_ID", "")
        if env_spotify_id and "spotify" in self._providers:
            self._providers["spotify"].client_id = env_spotify_id
            self._providers["spotify"].client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")

        env_notion_id = os.getenv("NOTION_CLIENT_ID", "")
        if env_notion_id and "notion" in self._providers:
            self._providers["notion"].client_id = env_notion_id
            self._providers["notion"].client_secret = os.getenv("NOTION_CLIENT_SECRET", "")

        # PR11: Google + Microsoft client credentials come from env so
        # operators can wire real OAuth without hand-editing
        # ~/.feral/oauth_providers.json. Names match the docs.
        env_google_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
        if env_google_id and "google" in self._providers:
            self._providers["google"].client_id = env_google_id
            self._providers["google"].client_secret = os.getenv(
                "GOOGLE_OAUTH_CLIENT_SECRET", ""
            )
        env_ms_id = os.getenv("MICROSOFT_OAUTH_CLIENT_ID", "")
        if env_ms_id and "microsoft" in self._providers:
            self._providers["microsoft"].client_id = env_ms_id
            self._providers["microsoft"].client_secret = os.getenv(
                "MICROSOFT_OAUTH_CLIENT_SECRET", ""
            )

        # audit-r12 D9: Whoop + Oura credentials. Whoop requires both
        # client_id and client_secret on the refresh request per the
        # vendor docs; Oura same.
        env_whoop_id = os.getenv("WHOOP_OAUTH_CLIENT_ID", "")
        if env_whoop_id and "whoop" in self._providers:
            self._providers["whoop"].client_id = env_whoop_id
            self._providers["whoop"].client_secret = os.getenv(
                "WHOOP_OAUTH_CLIENT_SECRET", ""
            )
        env_oura_id = os.getenv("OURA_OAUTH_CLIENT_ID", "")
        if env_oura_id and "oura" in self._providers:
            self._providers["oura"].client_id = env_oura_id
            self._providers["oura"].client_secret = os.getenv(
                "OURA_OAUTH_CLIENT_SECRET", ""
            )

    def _load_tokens(self):
        """Load saved tokens from BlindVault or fallback JSON."""
        if self._vault:
            for provider_id in self._providers:
                token_json = self._vault.retrieve(f"oauth_{provider_id}", requester="oauth_manager")
                if token_json:
                    try:
                        self._tokens[provider_id] = json.loads(token_json)
                    except json.JSONDecodeError:
                        pass
        elif OAUTH_STATE_PATH.exists():
            try:
                self._tokens = json.loads(OAUTH_STATE_PATH.read_text())
            except Exception:
                pass

    def _save_token(self, provider_id: str, token_data: dict):
        self._tokens[provider_id] = token_data
        if self._vault:
            self._vault.store(
                f"oauth_{provider_id}",
                json.dumps(token_data),
                requester="oauth_manager",
            )
        else:
            OAUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            OAUTH_STATE_PATH.write_text(json.dumps(self._tokens, indent=2))
            os.chmod(OAUTH_STATE_PATH, 0o600)

    def get_provider(self, provider_id: str) -> Optional[OAuthProvider]:
        return self._providers.get(provider_id)

    def list_providers(self) -> list[dict]:
        result = []
        for pid, p in self._providers.items():
            connected = pid in self._tokens and bool(self._tokens[pid].get("access_token"))
            result.append({
                "id": pid,
                "name": p.name,
                "auth_type": p.auth_type,
                "connected": connected,
                "has_client_id": bool(p.client_id),
            })
        return result

    def build_authorize_url(self, provider_id: str) -> Optional[str]:
        """Generate the OAuth2 authorization URL with PKCE if supported."""
        provider = self._providers.get(provider_id)
        if not provider or provider.auth_type != "oauth2":
            return None
        if not provider.client_id:
            logger.warning(f"No client_id configured for {provider_id}")
            return None

        state = secrets.token_urlsafe(32)

        params = {
            "client_id": provider.client_id,
            "response_type": "code",
            "redirect_uri": provider.redirect_uri,
            "state": state,
        }

        if provider.scopes:
            params["scope"] = " ".join(provider.scopes)

        pending = {"provider_id": provider_id, "created": time.time()}

        if provider.pkce:
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode()).digest()
            ).rstrip(b"=").decode()
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
            pending["code_verifier"] = code_verifier

        self._pending_states[state] = pending

        url = f"{provider.auth_url}?{urlencode(params)}"
        logger.info(f"OAuth authorize URL generated for {provider_id}")
        return url

    async def handle_callback(self, state: str, code: str) -> dict:
        """Exchange the authorization code for tokens."""
        pending = self._pending_states.pop(state, None)
        if not pending:
            return {"error": "Invalid or expired state parameter"}

        provider_id = pending["provider_id"]
        provider = self._providers.get(provider_id)
        if not provider:
            return {"error": f"Unknown provider: {provider_id}"}

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": provider.redirect_uri,
        }

        if provider.pkce:
            data["code_verifier"] = pending.get("code_verifier", "")
            data["client_id"] = provider.client_id
        else:
            data["client_id"] = provider.client_id
            if provider.client_secret:
                data["client_secret"] = provider.client_secret

        try:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            if provider_id == "notion" and provider.client_secret:
                creds = base64.b64encode(
                    f"{provider.client_id}:{provider.client_secret}".encode()
                ).decode()
                headers["Authorization"] = f"Basic {creds}"

            resp = await self._http.post(provider.token_url, data=data, headers=headers)
            resp.raise_for_status()
            token_data = resp.json()
            token_data["obtained_at"] = time.time()
            self._save_token(provider_id, token_data)
            logger.info(f"OAuth tokens obtained for {provider_id}")
            return {"success": True, "provider": provider_id}
        except Exception as e:
            logger.error(f"OAuth token exchange failed for {provider_id}: {e}")
            return {"error": str(e)}

    async def get_token(self, provider_id: str) -> Optional[str]:
        """Get a valid access token, refreshing if expired."""
        token_data = self._tokens.get(provider_id)
        if not token_data:
            return None

        access_token = token_data.get("access_token", "")
        if not access_token:
            return None

        expires_in = token_data.get("expires_in", 3600)
        obtained_at = token_data.get("obtained_at", 0)
        if time.time() > obtained_at + expires_in - 60:
            refreshed = await self._refresh_token(provider_id)
            if refreshed:
                return self._tokens[provider_id].get("access_token")
            return None

        return access_token

    async def _refresh_token(self, provider_id: str) -> bool:
        """Use the refresh_token to get a new access_token."""
        token_data = self._tokens.get(provider_id, {})
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            logger.warning(f"No refresh token for {provider_id}")
            return False

        provider = self._providers.get(provider_id)
        if not provider:
            return False

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": provider.client_id,
        }
        if provider.client_secret:
            data["client_secret"] = provider.client_secret

        try:
            resp = await self._http.post(
                provider.token_url, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            new_tokens = resp.json()
            new_tokens["obtained_at"] = time.time()
            if "refresh_token" not in new_tokens:
                new_tokens["refresh_token"] = refresh_token
            self._save_token(provider_id, new_tokens)
            logger.info(f"Token refreshed for {provider_id}")
            return True
        except Exception as e:
            logger.error(f"Token refresh failed for {provider_id}: {e}")
            return False

    def store_api_token(self, provider_id: str, token: str):
        """Store a long-lived API token (e.g., Home Assistant)."""
        self._save_token(provider_id, {
            "access_token": token,
            "token_type": "bearer",
            "obtained_at": time.time(),
            "expires_in": 999999999,
        })
        logger.info(f"API token stored for {provider_id}")

    def revoke_token(self, provider_id: str):
        self._tokens.pop(provider_id, None)
        if self._vault:
            self._vault.revoke(f"oauth_{provider_id}", requester="oauth_manager")

    def is_connected(self, provider_id: str) -> bool:
        return provider_id in self._tokens and bool(
            self._tokens[provider_id].get("access_token")
        )

    def status(self) -> dict:
        return {
            "providers": len(self._providers),
            "connected": [pid for pid in self._tokens if self.is_connected(pid)],
            "pending_flows": len(self._pending_states),
        }

    async def close(self):
        await self._http.aclose()
