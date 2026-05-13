"""PR 11 gap-fill: five new manifests for skill ids the brain
actually registers from integrations/.

The integration backends were live for months but had no manifests, so
the orchestrator never advertised them to the LLM and the skill
registry could not gate them. This test pins:

* Manifests parse via SkillManifest (Pydantic).
* Endpoint ids match the dispatch table of each backing integration —
  if a backend renames a method, the manifest test fails on the next
  CI run, not silently in production.
* Read endpoints declare safety_tier='safe' + read_only_hint=True.
* Mutating endpoints declare safety_tier='confirm' +
  requires_user_approval=True so PR 6's resolver enforces them.
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from models.skill_manifest import SkillManifest  # noqa: E402

MANIFEST_ROOT = ROOT / "skills" / "manifests"


def _load(skill_id: str) -> SkillManifest:
    raw = json.loads((MANIFEST_ROOT / f"{skill_id}.json").read_text())
    return SkillManifest(**raw)


def _backend_dispatch_keys(module_path: str, class_name: str) -> set[str]:
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    src = inspect.getsource(cls.execute)
    keys: set[str] = set()
    for line in src.splitlines():
        line = line.strip()
        if line.startswith('"') and ":" in line:
            try:
                key = line.split('"', 2)[1]
                keys.add(key)
            except Exception:
                pass
    return keys


# ── parses + endpoint id coverage ───────────────────────────────────


@pytest.mark.parametrize("skill_id,module,cls", [
    ("email", "integrations.email", "EmailIntegration"),
    ("google_drive", "integrations.google_drive", "GoogleDriveIntegration"),
    ("google_contacts", "integrations.google_contacts", "GoogleContactsIntegration"),
    ("microsoft365", "integrations.microsoft365", "Microsoft365Integration"),
    ("notion", "integrations.notion", "NotionIntegration"),
])
def test_manifest_matches_backend_dispatch(skill_id, module, cls):
    manifest = _load(skill_id)
    manifest_endpoint_ids = {e.id for e in manifest.endpoints}
    backend_dispatch = _backend_dispatch_keys(module, cls)
    # Every endpoint in the manifest must exist in the backend so the
    # LLM never advertises a method we can't dispatch.
    missing_in_backend = manifest_endpoint_ids - backend_dispatch
    assert not missing_in_backend, (
        f"{skill_id} manifest advertises {sorted(missing_in_backend)} "
        f"but the backend dispatch table has no implementation."
    )


# ── safety tier wiring ──────────────────────────────────────────────


WRITE_ENDPOINTS = {
    "email": {"send_email"},
    "google_drive": {"upload_file", "create_folder"},
    "microsoft365": {"send_mail", "create_event"},
    "notion": {"create_page", "update_page", "create_database_entry"},
}


def test_write_endpoints_require_approval():
    for skill_id, write_ids in WRITE_ENDPOINTS.items():
        manifest = _load(skill_id)
        for ep in manifest.endpoints:
            if ep.id in write_ids:
                assert ep.safety_tier == "confirm", (
                    f"{skill_id}.{ep.id}: write endpoint must be 'confirm' tier"
                )
                assert ep.requires_user_approval is True, (
                    f"{skill_id}.{ep.id}: write endpoint must require approval"
                )


def test_read_endpoints_marked_safe_and_read_only():
    safe_overrides = {
        # download_file produces local bytes; the manifest explicitly
        # marks it safe at the manifest layer — surface-level gating
        # (e.g. mcp surface deny) handles the cross-surface case.
        ("google_drive", "download_file"),
        # draft_email writes a draft to the user's own Drafts folder.
        # Reversible, no external visibility — kept safe-tier but not
        # asserted as read_only.
        ("email", "draft_email"),
    }
    for skill_id in ("email", "google_drive", "google_contacts", "microsoft365", "notion"):
        manifest = _load(skill_id)
        write_ids = WRITE_ENDPOINTS.get(skill_id, set())
        for ep in manifest.endpoints:
            if ep.id in write_ids:
                continue
            assert ep.safety_tier == "safe", (
                f"{skill_id}.{ep.id}: read endpoint should be 'safe'"
            )
            if (skill_id, ep.id) in safe_overrides:
                continue
            assert ep.read_only_hint is True, (
                f"{skill_id}.{ep.id}: read endpoint should set read_only_hint=True"
            )


# ── safety_resolver agrees ──────────────────────────────────────────


def test_safety_resolver_picks_up_manifest_tiers():
    """PR 6's resolver should map the new manifests to CONFIRM for
    writes and AUTO for reads when given the right registry."""
    from security.safety_resolver import LEVEL_AUTO, LEVEL_CONFIRM, resolve_policy

    class _Registry:
        def __init__(self):
            self.skills = {sid: _load(sid) for sid in WRITE_ENDPOINTS}

    reg = _Registry()
    # write
    d = resolve_policy("email__send_email", args={"to": "x", "subject": "y", "body": "z"}, surface="websocket", registry=reg)
    assert d.level == LEVEL_CONFIRM
    # read
    d = resolve_policy("email__list_inbox", args={}, surface="websocket", registry=reg)
    assert d.level == LEVEL_AUTO
