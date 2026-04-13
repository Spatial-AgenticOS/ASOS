"""
FERAL Push Notification Channel — Firebase Cloud Messaging (Android) + APNs (iOS)
==================================================================================
Sends push notifications through FCM v1 HTTP API and APNs HTTP/2.
Device tokens are stored in a local SQLite database.
Gracefully degrades when credentials are not configured.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from config.loader import feral_data_home

logger = logging.getLogger("feral.channels.push")


def _db_path() -> Path:
    base = feral_data_home()
    base.mkdir(parents=True, exist_ok=True)
    return base / "push_tokens.db"


class PushChannel:
    """Push notification dispatcher for FCM (Android) and APNs (iOS)."""

    def __init__(self) -> None:
        self._firebase_creds_path: str = os.environ.get("FERAL_FIREBASE_CREDENTIALS", "")
        self._apns_key_path: str = os.environ.get("FERAL_APNS_KEY_PATH", "")
        self._apns_team_id: str = os.environ.get("FERAL_APNS_TEAM_ID", "")
        self._apns_key_id: str = os.environ.get("FERAL_APNS_KEY_ID", "")
        self._apns_environment: str = os.environ.get("FERAL_APNS_ENVIRONMENT", "production")
        self._firebase_project_id: Optional[str] = None
        self._firebase_token: Optional[str] = None
        self._firebase_token_expiry: float = 0.0
        self._apns_token: Optional[str] = None
        self._apns_token_expiry: float = 0.0
        self._lock = threading.Lock()

        self._conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

        if self._firebase_creds_path and Path(self._firebase_creds_path).exists():
            try:
                with open(self._firebase_creds_path) as f:
                    sa = json.load(f)
                self._firebase_project_id = sa.get("project_id")
                logger.info(f"Firebase credentials loaded (project: {self._firebase_project_id})")
            except Exception as exc:
                logger.warning(f"Failed to load Firebase credentials: {exc}")
        else:
            logger.warning("FERAL_FIREBASE_CREDENTIALS not set or file missing — FCM disabled")

        if not self._apns_key_path or not Path(self._apns_key_path).exists():
            logger.warning("FERAL_APNS_KEY_PATH not set or file missing — APNs disabled")

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    token TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'fcm',
                    registered_at REAL NOT NULL,
                    UNIQUE(user_id, token)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_device_user ON device_tokens (user_id)"
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ─── Device Registration ───

    def register_device(self, user_id: str, token: str, platform: str = "fcm") -> dict[str, Any]:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO device_tokens (user_id, token, platform, registered_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, token, platform, now),
            )
            self._conn.commit()
        logger.info(f"Registered device token for user={user_id} platform={platform}")
        return {"success": True, "user_id": user_id, "platform": platform}

    def get_tokens(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT token, platform, registered_at FROM device_tokens WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [{"token": r["token"], "platform": r["platform"], "registered_at": r["registered_at"]} for r in rows]

    # ─── Sending ───

    def send_push(
        self,
        device_token: str,
        title: str,
        body: str,
        data: Optional[dict[str, str]] = None,
        platform: str = "fcm",
    ) -> dict[str, Any]:
        if platform == "apns":
            return self._send_apns(device_token, title, body, data)
        return self._send_fcm(device_token, title, body, data)

    def broadcast(
        self,
        user_id: str,
        title: str,
        body: str,
        data: Optional[dict[str, str]] = None,
    ) -> list[dict[str, Any]]:
        """Send push notification to all registered devices for a user."""
        tokens = self.get_tokens(user_id)
        if not tokens:
            logger.info(f"No device tokens for user={user_id}")
            return [{"success": False, "error": "no registered devices"}]
        results: list[dict[str, Any]] = []
        for entry in tokens:
            result = self.send_push(entry["token"], title, body, data, platform=entry["platform"])
            results.append(result)
        return results

    # ─── FCM v1 HTTP API ───

    def _get_fcm_bearer_token(self) -> Optional[str]:
        """Obtain an OAuth2 bearer token for FCM using google-auth, if available."""
        if time.time() < self._firebase_token_expiry and self._firebase_token:
            return self._firebase_token

        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests

            scopes = ["https://www.googleapis.com/auth/firebase.messaging"]
            creds = service_account.Credentials.from_service_account_file(
                self._firebase_creds_path, scopes=scopes,
            )
            creds.refresh(google.auth.transport.requests.Request())
            self._firebase_token = creds.token
            self._firebase_token_expiry = time.time() + 3300  # ~55 min
            return self._firebase_token
        except ImportError:
            logger.warning("google-auth not installed — cannot authenticate FCM requests")
            return None
        except Exception as exc:
            logger.error(f"FCM token refresh failed: {exc}")
            return None

    def _send_fcm(
        self, token: str, title: str, body: str, data: Optional[dict[str, str]],
    ) -> dict[str, Any]:
        if not self._firebase_project_id:
            return {"success": False, "error": "Firebase project not configured"}

        bearer = self._get_fcm_bearer_token()
        if not bearer:
            return {"success": False, "error": "Could not obtain FCM bearer token"}

        url = f"https://fcm.googleapis.com/v1/projects/{self._firebase_project_id}/messages:send"
        message: dict[str, Any] = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
            }
        }
        if data:
            message["message"]["data"] = {k: str(v) for k, v in data.items()}

        try:
            import httpx
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=message, headers={"Authorization": f"Bearer {bearer}"})
            if resp.status_code == 200:
                logger.info(f"FCM push sent to token={token[:12]}…")
                return {"success": True, "platform": "fcm", "status_code": resp.status_code}
            logger.warning(f"FCM push failed ({resp.status_code}): {resp.text[:300]}")
            return {"success": False, "platform": "fcm", "status_code": resp.status_code, "error": resp.text[:300]}
        except ImportError:
            logger.warning("httpx not installed — cannot send FCM push")
            return {"success": False, "error": "httpx not installed"}
        except Exception as exc:
            logger.error(f"FCM push error: {exc}")
            return {"success": False, "error": str(exc)}

    # ─── APNs HTTP/2 ───

    def _get_apns_token(self) -> Optional[str]:
        """Return a cached APNs JWT, refreshing when older than 50 minutes."""
        if self._apns_token and time.time() < self._apns_token_expiry:
            return self._apns_token

        if not self._apns_team_id or not self._apns_key_id:
            logger.warning("FERAL_APNS_TEAM_ID or FERAL_APNS_KEY_ID not set")
            return None

        try:
            import jwt
        except ImportError:
            logger.warning("PyJWT not installed — cannot sign APNs token")
            return None

        key_path = Path(self._apns_key_path)
        if not key_path.exists():
            logger.warning(f"APNs .p8 key not found at {self._apns_key_path}")
            return None

        try:
            private_key = key_path.read_text()
            now = int(time.time())
            token = jwt.encode(
                {"iss": self._apns_team_id, "iat": now},
                private_key,
                algorithm="ES256",
                headers={"kid": self._apns_key_id},
            )
            self._apns_token = token
            self._apns_token_expiry = time.time() + 3000  # 50 min cache
            logger.info("APNs JWT signed and cached")
            return self._apns_token
        except Exception as exc:
            logger.error(f"APNs JWT signing failed: {exc}")
            return None

    def _send_apns(
        self, token: str, title: str, body: str, data: Optional[dict[str, str]],
    ) -> dict[str, Any]:
        if not self._apns_key_path or not Path(self._apns_key_path).exists():
            return {"success": False, "error": "APNs key not configured"}

        bearer = self._get_apns_token()
        if not bearer:
            return {"success": False, "error": "Could not obtain APNs bearer token"}

        payload: dict[str, Any] = {
            "aps": {"alert": {"title": title, "body": body}, "sound": "default"},
        }
        if data:
            for k, v in data.items():
                payload[k] = v

        if self._apns_environment == "sandbox":
            host = "api.sandbox.push.apple.com"
        else:
            host = "api.push.apple.com"

        try:
            import httpx
            url = f"https://{host}/3/device/{token}"
            headers = {
                "Authorization": f"bearer {bearer}",
                "apns-topic": data.get("bundle_id", "com.feral.app") if data else "com.feral.app",
                "apns-push-type": "alert",
                "apns-priority": "10",
            }
            with httpx.Client(http2=True, timeout=10.0) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                logger.info(f"APNs push sent to token={token[:12]}…")
                return {"success": True, "platform": "apns", "status_code": resp.status_code}
            logger.warning(f"APNs push failed ({resp.status_code}): {resp.text[:300]}")
            return {"success": False, "platform": "apns", "status_code": resp.status_code, "error": resp.text[:300]}
        except ImportError:
            logger.warning("httpx with h2 not available — cannot send APNs push")
            return {"success": False, "error": "httpx with HTTP/2 support not installed"}
        except Exception as exc:
            logger.error(f"APNs push error: {exc}")
            return {"success": False, "error": str(exc)}
