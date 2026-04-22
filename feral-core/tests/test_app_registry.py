"""Tests for AppRegistry — install, list, uninstall, action validation."""

from __future__ import annotations

import json

import pytest

from agents.app_registry import AppRegistry, AppRegistryError, HybridGenerator
from models.app_manifest import (
    ActionSpec,
    AppManifest,
    DataSchemaSpec,
    SurfaceSpec,
)
from models.skill_manifest import BrandProfile


def _sample_manifest(app_id: str = "demo-app") -> AppManifest:
    return AppManifest(
        app_id=app_id,
        version="1.0.0",
        author="feral-team",
        description="A tiny demo",
        brand=BrandProfile(name="Demo", primary_color="#4C1D95"),
        permissions=[],
        data_schemas=[
            DataSchemaSpec(schema_id="thread", schema={"type": "object"}),
        ],
        surfaces=[
            SurfaceSpec(
                surface_id="home",
                title="Home",
                kind="authored",
                template_root={
                    "type": "VStack",
                    "children": [
                        {"type": "Text", "value": "$data.greeting"},
                        {"type": "Button", "label": "Open", "action_id": "open"},
                    ],
                },
                action_contract=[
                    ActionSpec(action_id="open", handler="navigate", target="thread"),
                ],
            ),
            SurfaceSpec(
                surface_id="thread",
                title="Thread",
                kind="authored",
                template_root={
                    "type": "VStack",
                    "children": [{"type": "Text", "value": "$data.contact"}],
                },
                action_contract=[],
            ),
        ],
        entry_surface_id="home",
    )


def _write_manifest_dir(tmp_path, manifest: AppManifest):
    src = tmp_path / f"src-{manifest.app_id}"
    src.mkdir()
    manifest_json = src / "manifest.json"
    manifest_json.write_text(manifest.model_dump_json())
    return src


@pytest.fixture
def registry(tmp_path):
    db = tmp_path / "apps.db"
    apps_dir = tmp_path / "apps"
    reg = AppRegistry(
        db_path=str(db),
        apps_dir=apps_dir,
    )
    hybrid = HybridGenerator(cache_dir=tmp_path / "cache")
    reg.set_hybrid_generator(hybrid)
    return reg


class TestInstall:
    def test_install_from_dir_creates_row_and_copies(self, registry, tmp_path):
        src = _write_manifest_dir(tmp_path, _sample_manifest())
        app = registry.install_from_dir(src)
        assert app.app_id == "demo-app"
        assert app.version == "1.0.0"
        assert app.install_dir.exists()
        assert (app.install_dir / "manifest.json").is_file()

    def test_install_reads_yaml_when_present(self, registry, tmp_path):
        import importlib.util
        if importlib.util.find_spec("yaml") is None:
            pytest.skip("pyyaml not installed — yaml branch inaccessible")
        import yaml
        src = tmp_path / "src-yaml"
        src.mkdir()
        (src / "manifest.yaml").write_text(yaml.safe_dump(_sample_manifest().model_dump()))
        app = registry.install_from_dir(src)
        assert app.app_id == "demo-app"

    def test_install_overwrite_default_true(self, registry, tmp_path):
        src = _write_manifest_dir(tmp_path, _sample_manifest())
        registry.install_from_dir(src)
        # Second install w/ same app_id just overwrites, doesn't error.
        registry.install_from_dir(src)
        assert len(registry.list()) == 1

    def test_install_from_non_dir_raises(self, registry, tmp_path):
        with pytest.raises(AppRegistryError):
            registry.install_from_dir(tmp_path / "no-such")

    def test_install_rejects_missing_manifest(self, registry, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(AppRegistryError):
            registry.install_from_dir(empty)

    def test_install_rejects_invalid_manifest(self, registry, tmp_path):
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "manifest.json").write_text(json.dumps({"app_id": "nope"}))
        with pytest.raises(AppRegistryError):
            registry.install_from_dir(bad)

    def test_install_inlines_template_root_file_ref(self, registry, tmp_path):
        manifest_dict = _sample_manifest().model_dump()
        # Move one surface's template into a sibling file.
        manifest_dict["surfaces"][1]["template_root"] = "surfaces/thread.sdui.json"
        src = tmp_path / "src-ref"
        src.mkdir()
        (src / "surfaces").mkdir()
        (src / "surfaces" / "thread.sdui.json").write_text(
            json.dumps({"type": "Text", "value": "hydrated"})
        )
        (src / "manifest.json").write_text(json.dumps(manifest_dict))
        app = registry.install_from_dir(src)
        thread_surface = app.manifest.get_surface("thread")
        assert thread_surface.template_root == {"type": "Text", "value": "hydrated"}


class TestListAndGet:
    def test_list_empty(self, registry):
        assert registry.list() == []

    def test_list_returns_installed_apps(self, registry, tmp_path):
        src_a = _write_manifest_dir(tmp_path, _sample_manifest("alpha-app"))
        src_b = _write_manifest_dir(tmp_path, _sample_manifest("beta-app"))
        registry.install_from_dir(src_a)
        registry.install_from_dir(src_b)
        ids = {a.app_id for a in registry.list()}
        assert ids == {"alpha-app", "beta-app"}

    def test_get_returns_none_when_missing(self, registry):
        assert registry.get("nope") is None

    def test_get_returns_installed(self, registry, tmp_path):
        registry.install_from_dir(_write_manifest_dir(tmp_path, _sample_manifest()))
        app = registry.get("demo-app")
        assert app is not None
        assert app.manifest.entry_surface_id == "home"


class TestUninstall:
    def test_uninstall_removes_row_and_dir(self, registry, tmp_path):
        registry.install_from_dir(_write_manifest_dir(tmp_path, _sample_manifest()))
        app = registry.get("demo-app")
        assert app is not None and app.install_dir.exists()
        assert registry.uninstall("demo-app") is True
        assert registry.get("demo-app") is None
        assert not app.install_dir.exists()

    def test_uninstall_unknown_returns_false(self, registry):
        assert registry.uninstall("not-there") is False


class TestValidateAction:
    def test_valid_action_returns_spec(self, registry, tmp_path):
        registry.install_from_dir(_write_manifest_dir(tmp_path, _sample_manifest()))
        spec = registry.validate_action("demo-app", "home", "open")
        assert spec.action_id == "open"
        assert spec.handler == "navigate"

    def test_unknown_app_raises(self, registry):
        with pytest.raises(AppRegistryError):
            registry.validate_action("ghost", "home", "open")

    def test_unknown_surface_raises(self, registry, tmp_path):
        registry.install_from_dir(_write_manifest_dir(tmp_path, _sample_manifest()))
        with pytest.raises(AppRegistryError):
            registry.validate_action("demo-app", "no-surface", "open")

    def test_unknown_action_raises(self, registry, tmp_path):
        registry.install_from_dir(_write_manifest_dir(tmp_path, _sample_manifest()))
        with pytest.raises(AppRegistryError) as exc:
            registry.validate_action("demo-app", "home", "evil")
        assert "evil" in str(exc.value)


class TestResolveAppAndSurface:
    def test_resolves_screen_id(self, registry):
        result = registry.resolve_app_and_surface("demo-app:home:session-abc")
        assert result == ("demo-app", "home")

    def test_rejects_bogus_screen_id(self, registry):
        assert registry.resolve_app_and_surface("") is None
        assert registry.resolve_app_and_surface("notacolon") is None


class TestOpenSurface:
    @pytest.mark.asyncio
    async def test_open_surface_hydrates_authored_template(self, registry, tmp_path):
        registry.install_from_dir(_write_manifest_dir(tmp_path, _sample_manifest()))
        out = await registry.open_surface(
            "demo-app", "home", data={"greeting": "hi there"},
        )
        assert out["app_id"] == "demo-app"
        assert out["surface_id"] == "home"
        assert "screen_id" in out and out["screen_id"].startswith("demo-app:home:")
        tree = out["root"]
        assert tree["children"][0]["value"] == "hi there"

    @pytest.mark.asyncio
    async def test_open_surface_requires_installed_app(self, registry):
        with pytest.raises(AppRegistryError):
            await registry.open_surface("nope", "home")

    @pytest.mark.asyncio
    async def test_open_surface_requires_known_surface(self, registry, tmp_path):
        registry.install_from_dir(_write_manifest_dir(tmp_path, _sample_manifest()))
        with pytest.raises(AppRegistryError):
            await registry.open_surface("demo-app", "ghost")
