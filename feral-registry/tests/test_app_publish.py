"""Schema + manifest-validator tests for kind=app.

End-to-end publish flow against a live FastAPI app is exercised by
``test_publish_flow.py``; that file uses an importlib.reload() pattern
that conflicts with SQLAlchemy's MetaData when a second async fixture
tries to redefine the same tables. Rather than duplicate the brittle
fixture here, this module validates the registry-side contract for
``kind="app"`` directly:

* ``Kind`` enum + ``ALL_KINDS`` advertise ``app``.
* ``Manifest.model_validate_json`` accepts an app manifest.
* ``validate_manifest_for_kind`` requires app_id + brand +
  entry_surface_id + surfaces (the four shape invariants the brain's
  AppRegistry then re-validates more strictly via AppManifest).

This is intentionally fast + deterministic; if a future commit fixes
the import-reload conflict, an HTTP-level publish test can land in a
new file without rewiring this one.
"""

from __future__ import annotations

import json

import pytest

from feral_registry.schemas import (
    ALL_KINDS,
    Kind,
    Manifest,
    validate_manifest_for_kind,
)


def _full_app_manifest() -> dict:
    return {
        "kind": "app",
        "name": "demo-app",
        "version": "1.0.0",
        "description": "A demo GenUI app",
        "author": "feral",
        "app_id": "demo-app",
        "brand": {"name": "Demo", "primary_color": "#5B21B6"},
        "entry_surface_id": "home",
        "surfaces": [
            {
                "surface_id": "home",
                "kind": "authored",
                "template_root": {"type": "Text", "value": "hello"},
                "action_contract": [],
            },
        ],
    }


class TestKindEnum:
    def test_app_in_all_kinds(self):
        assert "app" in ALL_KINDS

    def test_app_value_position_after_skill(self):
        # Stable ordering matters because some catalog UIs render kinds
        # in declaration order; locking the position prevents accidental
        # reshuffles.
        assert ALL_KINDS[0] == "skill"
        assert ALL_KINDS[1] == "app"

    def test_kind_literal_accepts_app(self):
        # Literal types don't expose __args__ at runtime in every
        # Python; instead we round-trip through Manifest which uses
        # the Literal as its `kind` field.
        m = Manifest(
            kind="app",
            name="x",
            version="1.0.0",
        )
        assert m.kind == "app"


class TestManifestParsing:
    def test_full_app_manifest_round_trips(self):
        raw = _full_app_manifest()
        m = Manifest.model_validate_json(json.dumps(raw))
        assert m.kind == "app"
        assert m.name == "demo-app"
        assert m.version == "1.0.0"

    def test_manifest_extras_preserved(self):
        # extra='allow' on Manifest means app-specific keys (app_id,
        # brand, surfaces, entry_surface_id) survive the round trip
        # unmodified — required because the registry stores the dump
        # verbatim and the brain reads brand/surfaces back at install
        # time.
        raw = _full_app_manifest()
        m = Manifest.model_validate_json(json.dumps(raw))
        dumped = m.model_dump()
        for key in ("app_id", "brand", "entry_surface_id", "surfaces"):
            assert key in dumped, f"missing app-specific key {key!r}"


class TestRequiredKeys:
    def test_full_app_manifest_passes_validator(self):
        raw = _full_app_manifest()
        m = Manifest.model_validate_json(json.dumps(raw))
        assert validate_manifest_for_kind(m) == []

    def test_missing_app_id_rejected(self):
        raw = _full_app_manifest()
        raw.pop("app_id")
        m = Manifest.model_validate_json(json.dumps(raw))
        missing = validate_manifest_for_kind(m)
        assert "app_id" in missing

    def test_missing_brand_rejected(self):
        raw = _full_app_manifest()
        raw.pop("brand")
        m = Manifest.model_validate_json(json.dumps(raw))
        missing = validate_manifest_for_kind(m)
        assert "brand" in missing

    def test_missing_entry_surface_rejected(self):
        raw = _full_app_manifest()
        raw.pop("entry_surface_id")
        m = Manifest.model_validate_json(json.dumps(raw))
        missing = validate_manifest_for_kind(m)
        assert "entry_surface_id" in missing

    def test_empty_surfaces_rejected(self):
        raw = _full_app_manifest()
        raw["surfaces"] = []
        m = Manifest.model_validate_json(json.dumps(raw))
        missing = validate_manifest_for_kind(m)
        assert "surfaces" in missing

    def test_skill_required_keys_unchanged(self):
        # Sanity check: extending the per-kind required map for "app"
        # mustn't accidentally add new "skill" requirements.
        m = Manifest(kind="skill", name="x", version="1.0.0")
        # Skill requires `skill_id` only.
        assert validate_manifest_for_kind(m) == ["skill_id"]
