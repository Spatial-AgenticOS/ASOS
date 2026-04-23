"""Tests for LMStudioProvider + setup local-provider install flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from providers.catalog import ProviderCatalog
from providers.lmstudio_provider import LMStudioProvider


class TestLMStudioProvider:
    def test_provider_id_and_defaults(self):
        p = LMStudioProvider()
        assert p.provider_id == "lmstudio"
        assert p.display_name == "LM Studio (local)"
        assert p._base_url == "http://localhost:1234/v1"

    def test_base_url_override(self):
        p = LMStudioProvider(base_url="http://10.0.0.5:1234/v1")
        assert p._base_url == "http://10.0.0.5:1234/v1"

    def test_seed_models_empty(self):
        # Explicitly empty — we refuse to show fake defaults for LM
        # Studio since the user controls which model is loaded in the
        # UI. The side-by-side table then correctly shows
        # "unreachable" or "no model loaded" instead of a lie.
        p = LMStudioProvider()
        assert p.list_models() == []

    @pytest.mark.asyncio
    async def test_refresh_models_parses_v1_models(self):
        p = LMStudioProvider()

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={
            "data": [
                {"id": "llama-3-8b-instruct"},
                {"id": "deepseek-coder-33b"},
            ],
        })

        with patch("providers.lmstudio_provider.httpx.AsyncClient") as Client:
            client = Client.return_value.__aenter__.return_value
            client.get = AsyncMock(return_value=resp)
            out = await p.refresh_models()
        assert set(out) == {"deepseek-coder-33b", "llama-3-8b-instruct"}
        assert p.list_models() == sorted(out)

    @pytest.mark.asyncio
    async def test_refresh_models_failure_keeps_cache(self):
        p = LMStudioProvider()
        p._models = ["cached-model"]

        with patch("providers.lmstudio_provider.httpx.AsyncClient") as Client:
            client = Client.return_value.__aenter__.return_value
            client.get = AsyncMock(side_effect=RuntimeError("offline"))
            out = await p.refresh_models()
        assert out == ["cached-model"]


class TestCatalogRegistersLMStudio:
    def test_descriptor_present(self, tmp_path):
        cat = ProviderCatalog(cache_path=tmp_path / "c.json")
        desc = cat.get_descriptor("lmstudio")
        assert desc is not None
        assert desc.supports_local is True
        assert desc.requires_api_key is False
        assert "1234" in desc.default_base_url

    def test_alias_resolves(self, tmp_path):
        cat = ProviderCatalog(cache_path=tmp_path / "c.json")
        assert cat.resolve_alias("LM Studio") == "lmstudio"
        assert cat.resolve_alias("lm-studio") == "lmstudio"

    def test_adapter_instantiated(self, tmp_path):
        cat = ProviderCatalog(cache_path=tmp_path / "c.json")
        adapter = cat.get_adapter("lmstudio")
        assert adapter is not None
        assert isinstance(adapter, LMStudioProvider)


class TestOllamaPullHelper:
    def test_cli_detection(self, monkeypatch):
        from cli.setup.local_providers import ollama_cli_installed

        monkeypatch.setattr("cli.setup.local_providers.shutil.which", lambda x: "/opt/bin/ollama")
        assert ollama_cli_installed() is True

        monkeypatch.setattr("cli.setup.local_providers.shutil.which", lambda x: None)
        assert ollama_cli_installed() is False

    @pytest.mark.asyncio
    async def test_pull_without_cli_raises(self, monkeypatch):
        from cli.setup.local_providers import ollama_pull_model

        monkeypatch.setattr("cli.setup.local_providers.shutil.which", lambda x: None)
        with pytest.raises(RuntimeError) as exc:
            await ollama_pull_model("llama3")
        assert "ollama" in str(exc.value)

    @pytest.mark.asyncio
    async def test_pull_streams_output(self, monkeypatch):
        from cli.setup import local_providers

        monkeypatch.setattr(local_providers.shutil, "which", lambda x: "/usr/bin/ollama")

        class FakeStdout:
            def __init__(self, lines):
                self._lines = iter(lines)

            async def readline(self):
                try:
                    return next(self._lines)
                except StopIteration:
                    return b""

        class FakeProc:
            def __init__(self):
                self.stdout = FakeStdout([b"pulling manifest\n", b"writing manifest\n"])

            async def wait(self):
                return 0

        async def fake_exec(*a, **kw):
            return FakeProc()

        monkeypatch.setattr(local_providers.asyncio, "create_subprocess_exec", fake_exec)

        lines: list[str] = []
        code = await local_providers.ollama_pull_model("llama3:8b", on_line=lines.append)
        assert code == 0
        assert "pulling manifest" in lines
        assert "writing manifest" in lines
