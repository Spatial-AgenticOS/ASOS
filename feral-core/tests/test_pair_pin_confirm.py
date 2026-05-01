"""Tests for the pair-pin-confirm PR (#61).

Cover the 4-digit PIN second factor on browser pairing:

- ``pair_device(require_pin=True)`` mints + persists a PIN.
- ``token_requires_pin(token)`` returns True only when a PIN was set.
- ``verify_pin`` accepts the right PIN, rejects wrong, expires after
  PIN_MAX_ATTEMPTS, marks the row pin_verified.
- ``token_pin_verified`` is True for legacy (no-PIN) tokens and only
  for verified PIN-requiring tokens otherwise.
- HTTP routes:
  - GET /api/devices/pair/url?pin=true → response includes pin field
  - GET /api/devices/pair/check?t=… → reports pin_required correctly
  - POST /api/devices/pair/verify_pin → 200 / 401 / 404 / 409
  - POST /api/devices/pair/complete → 401 pin_not_verified when PIN
    needed and not yet verified
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.no_auto_feral_home


# ── Unit: DevicePairingStore PIN methods ─────────────────────────────


@pytest.fixture
def store(tmp_path):
    from security.device_pairing import DevicePairingStore
    return DevicePairingStore(db_path=str(tmp_path / "pairs.db"))


def test_pair_device_without_pin_has_no_pin_required(store):
    result = store.pair_device("phone-A", kind="browser")
    assert result["pin_required"] is False
    assert "pin" not in result
    assert store.token_requires_pin(result["token"]) is False
    # Legacy: tokens without PIN are immediately considered "verified"
    # so the existing /pair/complete flow works for them.
    assert store.token_pin_verified(result["token"]) is True


def test_pair_device_with_pin_returns_plaintext_once(store):
    result = store.pair_device("phone-B", kind="browser", require_pin=True)
    assert result["pin_required"] is True
    assert "pin" in result
    pin = result["pin"]
    # PIN_DIGITS default 4 — zero-padded.
    assert len(pin) == store.PIN_DIGITS
    assert pin.isdigit()
    # token_requires_pin agrees.
    assert store.token_requires_pin(result["token"]) is True
    # Not verified yet (no /verify_pin call yet).
    assert store.token_pin_verified(result["token"]) is False


def test_verify_pin_accepts_correct(store):
    result = store.pair_device("phone-C", kind="browser", require_pin=True)
    ok, reason = store.verify_pin(result["token"], result["pin"])
    assert ok is True
    assert reason == "verified"
    # Subsequent token_pin_verified is True.
    assert store.token_pin_verified(result["token"]) is True


def test_verify_pin_wrong_increments_attempts(store):
    result = store.pair_device("phone-D", kind="browser", require_pin=True)
    real_pin = result["pin"]
    wrong = "9999" if real_pin != "9999" else "0000"
    ok, reason = store.verify_pin(result["token"], wrong)
    assert ok is False
    assert reason == "wrong_pin"
    # Token still exists; can keep trying (until exhausted).
    assert store.token_requires_pin(result["token"]) is True


def test_verify_pin_exhausts_after_PIN_MAX_ATTEMPTS_wrong(store):
    result = store.pair_device("phone-E", kind="browser", require_pin=True)
    real_pin = result["pin"]
    wrong = "9999" if real_pin != "9999" else "0000"
    last_reason = None
    for _ in range(store.PIN_MAX_ATTEMPTS):
        ok, reason = store.verify_pin(result["token"], wrong)
        last_reason = reason
        assert ok is False
    # Final reason must be "exhausted"; token row is gone.
    assert last_reason == "exhausted"
    # token_requires_pin returns False because the row no longer exists
    # (we silently report no-pin-needed for unknown tokens to avoid
    # leaking which tokens exist).
    assert store.token_requires_pin(result["token"]) is False


def test_verify_pin_unknown_token_returns_unknown_token(store):
    ok, reason = store.verify_pin("nonexistent" * 8, "0000")
    assert ok is False
    assert reason == "unknown_token"


def test_verify_pin_no_pin_required_returns_no_pin_required(store):
    """Calling verify_pin on a token that wasn't issued with a PIN
    should NOT silently succeed — return ``no_pin_required`` so the
    phone form can detect the misconfiguration."""
    result = store.pair_device("phone-F", kind="browser")  # require_pin=False
    ok, reason = store.verify_pin(result["token"], "1234")
    assert ok is False
    assert reason == "no_pin_required"


# ── HTTP routes ─────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FERAL_HOME", str(tmp_path))
    from config.loader import ConfigLoader
    from security.device_pairing import DevicePairingStore

    config = ConfigLoader(project_dir=str(tmp_path))
    config.discover()
    # Phone-as-peer's pair URL resolver refuses to emit a pair URL in
    # Mode B (localhost) since localhost can't be reached from a phone.
    # Set Mode A so the PIN tests exercise the full /pair/url path.
    config.update_settings("access", "pairing_mode", "local")
    store = DevicePairingStore(db_path=str(tmp_path / "pairs.db"))

    mock_state = MagicMock()
    mock_state.config = config
    mock_state.device_pairing_store = store

    with (
        patch("api.state.state", mock_state),
        patch("api.routes.devices.state", mock_state),
    ):
        from api.server import app
        yield TestClient(app, raise_server_exceptions=True), store


def test_pair_url_with_pin_query_returns_pin_field(client):
    c, _ = client
    r = c.get("/api/devices/pair/url?name=phone&pin=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pin_required"] is True
    assert "pin" in body
    assert len(body["pin"]) == 4
    assert body["pin"].isdigit()


def test_pair_url_without_pin_query_omits_pin_field(client):
    c, _ = client
    r = c.get("/api/devices/pair/url?name=phone")
    assert r.status_code == 200
    body = r.json()
    assert body["pin_required"] is False
    assert "pin" not in body


def test_pair_check_reports_pin_required(client):
    c, store = client
    res = store.pair_device("phone", kind="browser", require_pin=True)
    r = c.get(f"/api/devices/pair/check?t={res['token']}")
    assert r.status_code == 200
    body = r.json()
    assert body["pin_required"] is True
    assert body["pin_length"] == 4


def test_pair_check_unknown_token_reports_no_pin_required(client):
    c, _ = client
    r = c.get("/api/devices/pair/check?t=nope")
    assert r.status_code == 200
    body = r.json()
    # We deliberately do NOT leak whether a token exists via this
    # endpoint; unknown tokens look the same as no-PIN tokens.
    assert body["pin_required"] is False


def test_verify_pin_correct_returns_200(client):
    c, store = client
    res = store.pair_device("phone", kind="browser", require_pin=True)
    r = c.post(
        "/api/devices/pair/verify_pin",
        json={"token": res["token"], "pin": res["pin"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True


def test_verify_pin_wrong_returns_401(client):
    c, store = client
    res = store.pair_device("phone", kind="browser", require_pin=True)
    real = res["pin"]
    wrong = "9999" if real != "9999" else "0000"
    r = c.post(
        "/api/devices/pair/verify_pin",
        json={"token": res["token"], "pin": wrong},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "wrong_pin"


def test_verify_pin_no_pin_returns_409(client):
    c, store = client
    res = store.pair_device("phone", kind="browser")  # no PIN
    r = c.post(
        "/api/devices/pair/verify_pin",
        json={"token": res["token"], "pin": "1234"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "no_pin_required"


def test_pair_complete_blocked_without_pin_when_required(client):
    c, store = client
    res = store.pair_device("phone", kind="browser", require_pin=True)
    r = c.post("/api/devices/pair/complete", json={"token": res["token"]})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "pin_not_verified"


def test_pair_complete_works_after_verify_pin(client):
    c, store = client
    res = store.pair_device("phone", kind="browser", require_pin=True)
    rv = c.post(
        "/api/devices/pair/verify_pin",
        json={"token": res["token"], "pin": res["pin"]},
    )
    assert rv.status_code == 200
    rc = c.post("/api/devices/pair/complete", json={"token": res["token"]})
    assert rc.status_code == 200, rc.text
    assert rc.json()["success"] is True


def test_pair_complete_legacy_no_pin_token_works_unchanged(client):
    """Legacy tokens (no PIN) must still complete via /complete without
    any verify_pin call — this PR is additive."""
    c, store = client
    res = store.pair_device("phone", kind="browser")
    r = c.post("/api/devices/pair/complete", json={"token": res["token"]})
    assert r.status_code == 200
    assert r.json()["success"] is True
