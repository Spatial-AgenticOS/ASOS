"""
Deep tests for cli.setup_wizard: step flow, mocked I/O, validation, first-run, skips.

All filesystem and stdin operations are mocked; no real ~/.feral writes.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cli.setup_wizard as sw
from cli.setup_wizard import (
    TOOL_KEYS,
    OnboardWizard,
    OnboardWizardPlain,
)

pytestmark = pytest.mark.no_auto_feral_home


@pytest.fixture(autouse=True)
def _clear_openai_api_key_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# ── In-memory path shim (no real file I/O) ────────────────────────────────────


class _FakePath:
    """Minimal pathlib-like object backed by a string-keyed dict."""

    __slots__ = ("_storage", "_parts")

    def __init__(self, storage: dict[str, str], parts: tuple[str, ...] = ()):
        self._storage = storage
        self._parts = parts

    def __truediv__(self, other: str) -> _FakePath:
        return _FakePath(self._storage, self._parts + (str(other),))

    @property
    def _key(self) -> str:
        return "/".join(self._parts) if self._parts else "."

    def mkdir(self, parents: bool = True, exist_ok: bool = True) -> None:
        return None

    def exists(self) -> bool:
        return self._key in self._storage

    def read_text(self, encoding: str | None = None) -> str:
        return self._storage.get(self._key, "")

    def write_text(self, data: str, encoding: str | None = None) -> None:
        self._storage[self._key] = data

    def chmod(self, mode: int) -> None:
        self._storage[f"{self._key}__chmod__"] = str(mode)


@pytest.fixture
def fake_feral(monkeypatch):
    """Isolated fake home; patches module-level FERAL_HOME."""
    storage: dict[str, str] = {}
    root = _FakePath(storage)
    monkeypatch.setattr(sw, "FERAL_HOME", root)
    return storage, root


@contextmanager
def _patch_progress():
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock())
    cm.__exit__ = MagicMock(return_value=False)
    with patch("cli.setup_wizard.Progress", return_value=cm):
        yield


def _fake_path_exists(storage: dict, name: str) -> bool:
    return name in storage


# ── First run / returning user ────────────────────────────────────────────────


def test_first_run_no_credentials_file_yields_empty_creds(fake_feral):
    """No prior credentials.json → _load_existing_creds leaves creds empty."""
    storage, _root = fake_feral
    assert "credentials.json" not in storage
    w = OnboardWizard(MagicMock())
    w._load_existing_creds()
    assert w.creds == {}


def test_returning_user_credentials_json_loaded_into_creds(fake_feral):
    """Existing credentials.json is parsed into wizard.creds before steps."""
    storage, _ = fake_feral
    prior = {"OPENAI_API_KEY": "sk-existing-12345678901234567890"}
    storage["credentials.json"] = json.dumps(prior)
    w = OnboardWizard(MagicMock())
    w._load_existing_creds()
    assert w.creds == prior
    assert _fake_path_exists(storage, "credentials.json")


def test_load_existing_creds_malformed_json_falls_back_empty(fake_feral):
    storage, _ = fake_feral
    storage["credentials.json"] = "{not json"
    w = OnboardWizard(MagicMock())
    w._load_existing_creds()
    assert w.creds == {}


# ── Step progression & API key flow (Rich) ────────────────────────────────────


@pytest.mark.asyncio
async def test_wizard_step_progression_provider_then_model(fake_feral):
    """Provider step sets provider/base_url; model step sets model on cloud path."""
    _storage, _root = fake_feral
    mock_console = MagicMock()
    w = OnboardWizard(mock_console)
    prompts = ["openai", "sk-12345678901234567890", "gpt-4.1"]
    with patch("cli.setup_wizard.Prompt.ask", side_effect=prompts):
        with patch("cli.setup_wizard.os.getenv", return_value=""):
            with patch.object(OnboardWizard, "_validate_key", new_callable=AsyncMock, return_value=True):
                with _patch_progress():
                    await w._step_provider()
                    await w._step_model()
    assert w.config["provider"] == "openai"
    assert w.config["model"] == "gpt-4.1"
    assert w.creds.get("OPENAI_API_KEY") == "sk-12345678901234567890"


@pytest.mark.asyncio
async def test_api_key_validation_succeeds_sets_cred_and_process_env(fake_feral):
    _storage, _root = fake_feral
    key = "sk-validated-key-12345678901234567890"
    w = OnboardWizard(MagicMock())
    with patch("cli.setup_wizard.Prompt.ask", side_effect=["openai", key]):
        with patch("cli.setup_wizard.os.getenv", return_value=""):
            with patch.object(OnboardWizard, "_validate_key", new_callable=AsyncMock, return_value=True):
                with _patch_progress():
                    await w._step_provider()
    assert w.creds["OPENAI_API_KEY"] == key
    assert os.environ.get("OPENAI_API_KEY") == key


@pytest.mark.asyncio
async def test_api_key_validation_failure_still_persists_key(fake_feral):
    _storage, _root = fake_feral
    key = "sk-maybe-invalid-12345678901234567890"
    w = OnboardWizard(MagicMock())
    with patch("cli.setup_wizard.Prompt.ask", side_effect=["openai", key]):
        with patch("cli.setup_wizard.os.getenv", return_value=""):
            with patch.object(OnboardWizard, "_validate_key", new_callable=AsyncMock, return_value=False):
                with _patch_progress():
                    await w._step_provider()
    assert w.creds["OPENAI_API_KEY"] == key


# ── Config generation (_save_all) ─────────────────────────────────────────────


def test_save_all_writes_credentials_config_and_settings(fake_feral):
    storage, _root = fake_feral
    w = OnboardWizard(MagicMock())
    w.creds = {"OPENAI_API_KEY": "sk-x"}
    w.config = {
        "provider": "openai",
        "model": "gpt-4.1",
        "base_url": "",
        "agent_name": "Tester",
        "multi_agent": False,
        "vlm_provider": "",
        "vlm_model": "",
        "local_preset": "",
        "phone_bridge_url": "",
        "glasses_model": "",
    }
    w._save_all()
    assert "credentials.json" in storage
    assert json.loads(storage["credentials.json"])["OPENAI_API_KEY"] == "sk-x"
    cfg = json.loads(storage["config.json"])
    assert cfg["provider"] == "openai" and cfg["model"] == "gpt-4.1"
    settings = json.loads(storage["settings.json"])
    assert settings["meta"]["setup_complete"] is True
    assert settings["llm"]["provider"] == "openai"
    assert settings["features"]["multi_agent"] is False


# ── About you: optional overwrite skip ────────────────────────────────────────


@pytest.mark.asyncio
async def test_about_you_keeps_existing_user_md_when_overwrite_declined(fake_feral):
    storage, _root = fake_feral
    original = "# Custom\n\nMy profile is unique.\n"
    storage["USER.md"] = original
    w = OnboardWizard(MagicMock())
    with patch("cli.setup_wizard.Confirm.ask", return_value=False):
        await w._step_about_you()
    assert storage["USER.md"] == original


@pytest.mark.asyncio
async def test_about_you_writes_when_no_existing_file(fake_feral):
    storage, _root = fake_feral
    w = OnboardWizard(MagicMock())
    with patch("cli.setup_wizard.Confirm.ask", return_value=False):
        with patch(
            "cli.setup_wizard.Prompt.ask",
            side_effect=[
                "Ada",
                "NYC",
                "English",
                "dev",
                "reading",
                "intermediate",
                "developer-tool",
                "concise",
                "Agent should remember I like tea.",
            ],
        ):
            await w._step_about_you()
    assert "USER.md" in storage
    body = storage["USER.md"]
    assert "Ada" in body and "NYC" in body
    assert "developer-tool" in body
    assert "tea" in body


# ── Device pairing & tool keys: skip optional sections ────────────────────────


@pytest.mark.asyncio
async def test_device_pairing_skipped_leaves_device_keys_empty(fake_feral):
    _storage, _root = fake_feral
    w = OnboardWizard(MagicMock())
    with patch("cli.setup_wizard.Confirm.ask", return_value=False):
        with patch("cli.setup_wizard._get_local_ip", return_value="10.0.0.1"):
            await w._step_device_pairing()
    assert w.config.get("phone_bridge_url", "") in ("", None)
    assert w.config.get("glasses_model", "") in ("", None)


@pytest.mark.asyncio
async def test_tool_keys_all_skipped_when_user_declines(fake_feral):
    _storage, _root = fake_feral
    w = OnboardWizard(MagicMock())
    w.creds = {}
    with patch("cli.setup_wizard.Confirm.ask", return_value=False):
        with patch("cli.setup_wizard.os.getenv", return_value=""):
            await w._step_tool_keys()
    assert w.creds == {}


# ── Error handling: bad / non-numeric input (plain wizard) ─────────────────────


def test_plain_wizard_non_numeric_provider_choice_falls_back_to_openai(fake_feral):
    storage, _root = fake_feral
    # 25 inputs: invalid provider idx → openai; then minimal path through plain run()
    # Provider + key + model, about-you×5, tech/use/comm, feral, personality×5, tools×8
    inputs = [
        "not-a-number",
        "sk-plainwizard-12345678901234567890",
        "",
        "", "", "", "", "",
        "", "", "",
        "",
        "", "", "", "", "",
    ]
    inputs.extend([""] * len(TOOL_KEYS))
    assert len(inputs) == 3 + 5 + 3 + 1 + 5 + len(TOOL_KEYS)

    it = iter(inputs)

    def _fake_input(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration as e:
            raise AssertionError(f"unexpected extra input() call: {prompt!r}") from e

    with patch("builtins.input", _fake_input):
        with patch("builtins.print"):
            with patch("cli.setup_wizard._get_local_ip", return_value="192.168.0.5"):
                asyncio.run(OnboardWizardPlain().run())

    assert json.loads(storage["credentials.json"])["OPENAI_API_KEY"].startswith("sk-plainwizard")
    cfg = json.loads(storage["config.json"])
    assert cfg["provider"] == "openai"
    settings = json.loads(storage["settings.json"])
    assert settings["meta"]["setup_complete"] is True


# ── Back navigation: not supported; skip = optional steps only ─────────────────


def test_rich_wizard_has_no_back_step_and_supports_optional_skip_only():
    """Linear wizard: no _step_back; optional flows use Confirm to skip."""
    assert not hasattr(OnboardWizard, "_step_back")
    assert hasattr(OnboardWizard, "_step_device_pairing")
    assert TOOL_KEYS and all(t.get("optional", True) for t in TOOL_KEYS)
