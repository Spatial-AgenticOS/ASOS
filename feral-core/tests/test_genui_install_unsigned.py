"""Install-time signing enforcement.

Spec contract:

* ``install_app(unsigned manifest, allow_unsigned=False)``
    → raises ``UnverifiedManifestError``.
* ``install_app(unsigned manifest, allow_unsigned=True)``
    → succeeds AND emits an audit log entry containing
      ``"unsigned_install"``.
* ``install_app(signed-and-verified manifest)``
    → succeeds with no warning.
"""

from __future__ import annotations

import json
import logging

import pytest

from agents.app_registry import (
    AppRegistry,
    HybridGenerator,
    UnverifiedManifestError,
)
from genui.manifest_signing import generate_keypair, sign
from models.app_manifest import (
    ActionSpec,
    AppManifest,
    SurfaceSpec,
)
from models.skill_manifest import BrandProfile


def _sample_manifest_dict(app_id: str = "demo-app") -> dict:
    manifest = AppManifest(
        app_id=app_id,
        version="1.0.0",
        author="feral-team",
        description="Test bundle",
        brand=BrandProfile(name="Demo", primary_color="#4C1D95"),
        permissions=[],
        surfaces=[
            SurfaceSpec(
                surface_id="home",
                title="Home",
                kind="authored",
                template_root={
                    "type": "VStack",
                    "children": [
                        {"type": "Text", "value": "$data.greeting"},
                        {
                            "type": "Button",
                            "label": "Hello",
                            "action_id": "hello",
                        },
                    ],
                },
                action_contract=[
                    ActionSpec(action_id="hello", handler="app_event"),
                ],
            ),
        ],
        entry_surface_id="home",
    )
    return json.loads(manifest.model_dump_json())


def _write_unsigned_bundle(tmp_path, app_id: str = "demo-app"):
    src = tmp_path / f"src-{app_id}"
    src.mkdir()
    manifest_dict = _sample_manifest_dict(app_id)
    (src / "manifest.json").write_text(json.dumps(manifest_dict))
    return src, manifest_dict


def _write_signed_bundle(tmp_path, app_id: str = "demo-app"):
    src, manifest_dict = _write_unsigned_bundle(tmp_path, app_id)
    sk, _pk = generate_keypair()
    signed = sign(manifest_dict, sk, key_id="test-key-do-not-commit")
    (src / "manifest.signed.json").write_text(signed.model_dump_json(indent=2))
    return src, signed


@pytest.fixture()
def registry(tmp_path):
    reg = AppRegistry(
        db_path=str(tmp_path / "apps.db"),
        apps_dir=tmp_path / "apps",
    )
    reg.set_hybrid_generator(HybridGenerator(cache_dir=tmp_path / "cache"))
    return reg


def test_install_unsigned_refused_by_default(registry, tmp_path):
    src, _ = _write_unsigned_bundle(tmp_path)
    with pytest.raises(UnverifiedManifestError) as exc_info:
        registry.install_app(src)
    assert "unsigned" in str(exc_info.value).lower()
    assert registry.get("demo-app") is None


def test_install_unsigned_with_opt_in_succeeds_and_audits(
    registry, tmp_path, caplog,
):
    src, _ = _write_unsigned_bundle(tmp_path)
    audit_events: list[dict] = []

    with caplog.at_level(logging.INFO, logger="feral.app_registry"):
        installed = registry.install_app(
            src,
            allow_unsigned=True,
            audit_callback=audit_events.append,
        )

    assert installed.app_id == "demo-app"
    assert registry.get("demo-app") is not None

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "unsigned_install" in log_text, log_text
    callback_events = [e.get("event") for e in audit_events]
    assert "unsigned_install" in callback_events, callback_events


def test_install_signed_succeeds_without_warning(registry, tmp_path, caplog):
    src, _signed = _write_signed_bundle(tmp_path)
    audit_events: list[dict] = []

    with caplog.at_level(logging.WARNING, logger="feral.app_registry"):
        installed = registry.install_app(
            src,
            allow_unsigned=False,
            audit_callback=audit_events.append,
        )

    assert installed.app_id == "demo-app"
    assert caplog.records == []
    callback_events = [e.get("event") for e in audit_events]
    assert "verified_install" in callback_events
    assert "unsigned_install" not in callback_events


def test_install_tampered_signed_manifest_refused(registry, tmp_path):
    src, signed = _write_signed_bundle(tmp_path)
    # Mutate the signed envelope on disk so the signature no longer matches.
    envelope = json.loads((src / "manifest.signed.json").read_text())
    envelope["manifest"]["author"] = "attacker-on-the-wire"
    (src / "manifest.signed.json").write_text(json.dumps(envelope))

    with pytest.raises(UnverifiedManifestError) as exc_info:
        registry.install_app(src, allow_unsigned=False)
    assert "signature" in str(exc_info.value).lower()


def test_install_wildcard_network_refused_without_high_trust(registry, tmp_path):
    """Wildcard network grant must be rejected even on a signed install
    unless the user explicitly opts in via user_high_trust + a non-empty
    publisher justification."""
    src = tmp_path / "src-wide"
    src.mkdir()
    manifest = _sample_manifest_dict("demo-app")
    manifest["permissions"] = {"network": ["*"]}  # no justification
    (src / "manifest.json").write_text(json.dumps(manifest))

    sk, _pk = generate_keypair()
    signed = sign(manifest, sk, key_id="test-key-do-not-commit")
    (src / "manifest.signed.json").write_text(signed.model_dump_json(indent=2))

    from genui.permissions_policy import PolicyViolation
    with pytest.raises(PolicyViolation):
        registry.install_app(src, allow_unsigned=False, user_high_trust=False)


def test_install_wildcard_network_allowed_with_justification_and_trust(
    registry, tmp_path,
):
    src = tmp_path / "src-wide-ok"
    src.mkdir()
    manifest = _sample_manifest_dict("demo-app-trusted")
    manifest["permissions"] = {
        "network": ["*"],
        "justification": "Realtime collaboration; needs arbitrary peer URLs.",
    }
    (src / "manifest.json").write_text(json.dumps(manifest))

    sk, _pk = generate_keypair()
    signed = sign(manifest, sk, key_id="test-key-do-not-commit")
    (src / "manifest.signed.json").write_text(signed.model_dump_json(indent=2))

    installed = registry.install_app(
        src,
        allow_unsigned=False,
        user_high_trust=True,
    )
    assert installed.app_id == "demo-app-trusted"
