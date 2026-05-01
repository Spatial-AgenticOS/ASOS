"""API contract tests for /api/apps."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.app_registry import AppRegistry, HybridGenerator
from models.app_manifest import (
    ActionSpec,
    AppManifest,
    SurfaceSpec,
)
from models.skill_manifest import BrandProfile


pytestmark = pytest.mark.no_auto_feral_home


def _write_manifest(path: Path, app_id: str = "demo-app") -> Path:
    src = path / f"src-{app_id}"
    src.mkdir()
    manifest = AppManifest(
        app_id=app_id,
        brand=BrandProfile(name="Demo"),
        data_schemas=[
            {
                "schema_id": "typed_payload",
                "schema": {
                    "type": "object",
                    "required": ["values"],
                    "properties": {
                        "values": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {
                                "text": {"type": "string", "minLength": 1},
                            },
                        }
                    },
                },
            }
        ],
        surfaces=[
            SurfaceSpec(
                surface_id="home",
                kind="authored",
                template_root={"type": "VStack", "children": [{"type": "Text", "value": "$data.msg"}]},
                action_contract=[
                    ActionSpec(action_id="hello", handler="app_event"),
                    ActionSpec(action_id="typed", handler="app_event", value_schema_ref="typed_payload"),
                ],
            ),
        ],
        entry_surface_id="home",
    )
    (src / "manifest.json").write_text(manifest.model_dump_json())
    return src


@pytest.fixture()
def client(tmp_path):
    registry = AppRegistry(
        db_path=str(tmp_path / "apps.db"),
        apps_dir=tmp_path / "apps",
    )
    hybrid = HybridGenerator(cache_dir=tmp_path / "cache")
    registry.set_hybrid_generator(hybrid)

    orchestrator = MagicMock()

    from unittest.mock import AsyncMock
    orchestrator.handle_ui_event = AsyncMock()

    mock = MagicMock()
    mock.app_registry = registry
    mock.orchestrator = orchestrator
    mock.sessions = {}

    with patch("api.state.state", mock), patch("api.routes.apps.state", mock):
        from api.server import app

        yield TestClient(app, raise_server_exceptions=False), registry, tmp_path


def test_list_empty(client):
    c, _registry, _tmp = client
    r = c.get("/api/apps")
    assert r.status_code == 200
    assert r.json() == {"count": 0, "apps": []}


def test_503_when_registry_missing():
    mock = MagicMock()
    mock.app_registry = None
    with patch("api.state.state", mock), patch("api.routes.apps.state", mock):
        from api.server import app
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/api/apps")
        assert r.status_code == 503


def test_install_from_local_dir(client):
    c, registry, tmp = client
    src = _write_manifest(tmp)
    r = c.post("/api/apps/install", json={"path": str(src), "unsigned": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["app"]["app_id"] == "demo-app"
    assert registry.get("demo-app") is not None


def test_install_rejects_without_source(client):
    c, _registry, _tmp = client
    r = c.post("/api/apps/install", json={})
    assert r.status_code == 400


def test_install_rejects_multiple_sources(client):
    c, _registry, _tmp = client
    r = c.post("/api/apps/install", json={"path": "/x", "git_url": "https://x/y.git"})
    assert r.status_code == 400


def test_install_registry_id_calls_registry_installer(client):
    c, registry, tmp = client
    src = _write_manifest(tmp, app_id="registry-app")
    with patch.object(
        registry,
        "install_from_registry",
        side_effect=lambda *args, **kwargs: registry.install_from_dir(src),
    ) as install_mock:
        r = c.post("/api/apps/install", json={"registry_id": "some-id"})
    assert r.status_code == 200, r.text
    assert install_mock.called
    assert r.json()["app"]["app_id"] == "registry-app"


def test_install_invalid_manifest_returns_400(client, tmp_path):
    c, _registry, _tmp = client
    bad = tmp_path / "bad-src"
    bad.mkdir()
    (bad / "manifest.json").write_text(json.dumps({"app_id": "nope"}))
    r = c.post("/api/apps/install", json={"path": str(bad), "unsigned": True})
    assert r.status_code == 400


def test_get_manifest(client):
    c, registry, tmp = client
    src = _write_manifest(tmp)
    c.post("/api/apps/install", json={"path": str(src), "unsigned": True})
    r = c.get("/api/apps/demo-app/manifest")
    assert r.status_code == 200
    assert r.json()["app_id"] == "demo-app"


def test_get_manifest_unknown_404(client):
    c, _registry, _tmp = client
    r = c.get("/api/apps/ghost/manifest")
    assert r.status_code == 404


def test_uninstall(client):
    c, registry, tmp = client
    src = _write_manifest(tmp)
    c.post("/api/apps/install", json={"path": str(src), "unsigned": True})
    r = c.delete("/api/apps/demo-app")
    assert r.status_code == 200
    assert registry.get("demo-app") is None


def test_uninstall_unknown_404(client):
    c, _registry, _tmp = client
    r = c.delete("/api/apps/ghost")
    assert r.status_code == 404


def test_open_returns_hydrated_surface(client):
    c, registry, tmp = client
    src = _write_manifest(tmp)
    c.post("/api/apps/install", json={"path": str(src), "unsigned": True})
    r = c.post("/api/apps/demo-app/open", json={"data": {"msg": "hi"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["surface_id"] == "home"
    assert body["root"]["children"][0]["value"] == "hi"


def test_open_unknown_app_404(client):
    c, _registry, _tmp = client
    r = c.post("/api/apps/ghost/open", json={})
    assert r.status_code == 404


def test_render_surface(client):
    c, registry, tmp = client
    src = _write_manifest(tmp)
    c.post("/api/apps/install", json={"path": str(src), "unsigned": True})
    r = c.post("/api/apps/demo-app/surfaces/home/render", json={"data": {"msg": "render!"}})
    assert r.status_code == 200
    assert r.json()["root"]["children"][0]["value"] == "render!"


def test_render_unknown_surface_returns_400(client):
    c, registry, tmp = client
    src = _write_manifest(tmp)
    c.post("/api/apps/install", json={"path": str(src), "unsigned": True})
    r = c.post("/api/apps/demo-app/surfaces/ghost/render", json={})
    assert r.status_code == 400


def test_dispatch_valid_action(client):
    c, registry, tmp = client
    src = _write_manifest(tmp)
    c.post("/api/apps/install", json={"path": str(src), "unsigned": True})
    r = c.post(
        "/api/apps/demo-app/dispatch",
        json={"surface_id": "home", "action_id": "hello", "value": None},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["handler"] == "app_event"


def test_dispatch_unknown_action_returns_400(client):
    c, registry, tmp = client
    src = _write_manifest(tmp)
    c.post("/api/apps/install", json={"path": str(src), "unsigned": True})
    r = c.post(
        "/api/apps/demo-app/dispatch",
        json={"surface_id": "home", "action_id": "evil"},
    )
    assert r.status_code == 400


def test_dispatch_schema_violation_returns_400(client):
    c, _registry, tmp = client
    src = _write_manifest(tmp)
    c.post("/api/apps/install", json={"path": str(src), "unsigned": True})
    r = c.post(
        "/api/apps/demo-app/dispatch",
        json={"surface_id": "home", "action_id": "typed", "value": {"values": {}}},
    )
    assert r.status_code == 400


def test_dispatch_unknown_app_returns_400(client):
    c, _registry, _tmp = client
    r = c.post(
        "/api/apps/ghost/dispatch",
        json={"surface_id": "home", "action_id": "evil"},
    )
    assert r.status_code == 400


def test_validate_accepts_valid_yaml_manifest(client):
    c, _registry, _tmp = client
    yaml_manifest = """
app_id: example-valid
version: 0.1.0
brand:
  name: Valid Demo
entry_surface_id: home
surfaces:
  - surface_id: home
    kind: authored
    template_root:
      type: stack
      children:
        - { type: text, value: "$data.msg" }
    action_contract:
      - action_id: hello
        handler: app_event
"""
    r = c.post("/api/apps/validate", json={"manifest": yaml_manifest})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["summary"]["app_id"] == "example-valid"
    assert "home" in body["summary"]["surfaces"]
    assert "hello" in body["summary"]["actions"]


def test_validate_accepts_valid_json_manifest(client):
    c, _registry, _tmp = client
    r = c.post(
        "/api/apps/validate",
        json={
            "manifest": json.dumps(
                {
                    "app_id": "example-j",
                    "brand": {"name": "J"},
                    "entry_surface_id": "home",
                    "surfaces": [
                        {
                            "surface_id": "home",
                            "kind": "authored",
                            "template_root": {"type": "stack"},
                        }
                    ],
                }
            )
        },
    )
    assert r.status_code == 200
    assert r.json()["summary"]["app_id"] == "example-j"


def test_validate_rejects_empty_manifest(client):
    c, _registry, _tmp = client
    r = c.post("/api/apps/validate", json={"manifest": ""})
    assert r.status_code == 400


def test_validate_rejects_non_mapping(client):
    c, _registry, _tmp = client
    r = c.post("/api/apps/validate", json={"manifest": "[1, 2, 3]"})
    assert r.status_code == 400


def test_validate_rejects_invalid_manifest(client):
    c, _registry, _tmp = client
    # Missing required fields → pydantic fails
    r = c.post("/api/apps/validate", json={"manifest": "app_id: only"})
    assert r.status_code == 400
