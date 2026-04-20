"""Contract: ``SkillEndpoint.method`` is a routing label, never a data branch.

This test pins down the invariant that was implicit after the ``CUSTOM``
method was added in ``fix(brain): restore CUSTOM-method skills`` (commit
af3eef2). The invariant is:

    1. The three first-party ``method: CUSTOM`` manifests load cleanly.
    2. Each has a Python backing class registered via
       ``skills.impl.get_implementation(skill_id)``.
    3. The backing classes route by ``endpoint_id``, NEVER by
       ``endpoint.method``. An AST scan of ``feral-core/skills/impl/``
       enforces this — adding ``if endpoint.method == "X"`` or
       ``ep.method == "X"`` anywhere under ``impl/`` fails this test.

The routing-label split lives in ``feral-core/skills/executor.py``:

  - ``WS_EXECUTE``  -> ``_execute_via_daemon``
  - ``GET/POST/..`` -> generic HTTP runner
  - ``CUSTOM/PYTHON`` -> resolved by ``skill_id`` to ``impl/*.py``
                         whose ``execute(endpoint_id, args, vault)``
                         routes per-endpoint internally.

If someone later adds ``endpoint.method`` branching inside an ``impl/``
module, they're re-introducing the bug this commit fixed.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.no_auto_feral_home


REPO = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO / "skills" / "manifests"
IMPL_DIR = REPO / "skills" / "impl"

CUSTOM_SKILLS = [
    ("workspace_scripts", "list_catalog"),
    ("messaging_channels", "list_channels"),
    ("self_introspection", "list_capabilities"),
]


@pytest.mark.parametrize("skill_id,_endpoint_id", CUSTOM_SKILLS)
def test_custom_method_manifest_loads(skill_id: str, _endpoint_id: str):
    """Each CUSTOM-method manifest parses under the live Pydantic model."""
    from models.skill_manifest import SkillManifest

    path = MANIFEST_DIR / f"{skill_id}.json"
    assert path.exists(), f"Expected manifest missing: {path}"
    data = json.loads(path.read_text())
    manifest = SkillManifest(**data)
    assert manifest.skill_id == skill_id
    # At least one endpoint uses method=CUSTOM — that's the whole point.
    assert any(ep.method == "CUSTOM" for ep in manifest.endpoints), (
        f"{skill_id} has no CUSTOM endpoints — manifest drifted"
    )


@pytest.mark.parametrize("skill_id,endpoint_id", CUSTOM_SKILLS)
def test_custom_skill_has_python_impl_and_does_not_raise(skill_id: str, endpoint_id: str):
    """Each CUSTOM skill resolves to a Python impl, and execute() returns a
    structured dict for a safe endpoint without raising — even if the full
    BrainState isn't initialised for this isolated test run."""
    import skills.impl  # triggers the auto-imports
    from skills.impl import get_implementation

    impl = get_implementation(skill_id)
    assert impl is not None, (
        f"No Python backing registered for {skill_id}. "
        f"Check skills/impl/__init__.py auto-imports."
    )

    result = asyncio.run(impl.execute(endpoint_id, {}, vault={}))
    assert isinstance(result, dict), f"{skill_id}.{endpoint_id} returned non-dict: {result!r}"
    assert "success" in result, (
        f"{skill_id}.{endpoint_id} missing 'success' key; contract: "
        "{success, status_code, data, error}"
    )


def test_no_impl_branches_on_endpoint_method():
    """AST guard: no module under feral-core/skills/impl/ may branch on
    endpoint.method (or the common alias ``ep.method``) equality. That's
    a re-introduction of the bug the CUSTOM-literal fix closed."""
    offenders: list[tuple[str, int, str]] = []

    for py in sorted(IMPL_DIR.rglob("*.py")):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            # Match `X.method == <any>` or `X.method != <any>` where X is a
            # Name — catches `endpoint.method`, `ep.method`, `e.method`.
            if not isinstance(node, ast.Compare):
                continue
            if not (isinstance(node.left, ast.Attribute) and node.left.attr == "method"):
                continue
            if not isinstance(node.left.value, ast.Name):
                continue
            # Only fail on equality-style comparisons (Eq, NotEq, In, NotIn).
            disallowed = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)
            if not any(isinstance(op, disallowed) for op in node.ops):
                continue
            offenders.append((str(py.relative_to(REPO)), node.lineno, ast.unparse(node)))

    assert not offenders, (
        "skills/impl/ modules must route by endpoint_id, not endpoint.method. "
        "Offending branches:\n"
        + "\n".join(f"  {path}:{lineno}  {src}" for path, lineno, src in offenders)
    )


def test_skill_endpoint_literal_still_includes_custom():
    """Regression guard: if someone removes ``CUSTOM`` from the Literal, the
    three first-party manifests silently stop loading at boot."""
    from models.skill_manifest import SkillEndpoint

    ep = SkillEndpoint(id="x", method="CUSTOM", url="/x", description="x")
    assert ep.method == "CUSTOM"
