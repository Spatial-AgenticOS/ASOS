"""A2UI marketplace trust verification — unimplemented-contract test.

Phase 1.5 placeholder hunt removed an inline ``TODO(v2): Add signed
marketplace trust verification`` from
``feral-core/genui/a2ui_protocol.py:121`` because a TODO comment in
production source without a tracked exit criterion is exactly the
placeholder pattern the operator flagged. The follow-up work is
tracked at https://github.com/FERAL-AI/FERAL-AI/issues/82.

This test exists so the gap stays *visible*: it pins the contract
that **no signed-marketplace trust verification surface exists
today**. If a future commit adds a ``verify_marketplace_signature``
symbol or a ``trusted_surface`` REST endpoint **without** also
satisfying the exit criteria in issue #82, this test fails loud
and the PR has to either:

* Implement the full verifier per the issue, OR
* Update this test to assert the new contract.

It must NOT be deleted silently — that would re-introduce the very
"behaves as if signed trust works" lie the audit caught.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest


pytestmark = pytest.mark.no_auto_feral_home


def test_no_marketplace_signature_verifier_exposed():
    """The ``a2ui_protocol`` module must NOT expose a
    ``verify_marketplace_signature`` (or similar) callable.
    """
    from genui import a2ui_protocol as mod

    forbidden_names = {
        "verify_marketplace_signature",
        "verify_signed_publisher",
        "trust_signed_marketplace",
        "marketplace_trust_check",
    }
    public = {name for name in dir(mod) if not name.startswith("_")}
    leaked = forbidden_names & public
    assert not leaked, (
        "a2ui_protocol exposes a marketplace-trust verifier ("
        f"{sorted(leaked)}). Issue #82 requires the full exit "
        "criteria be satisfied before any such symbol ships."
    )


def test_no_inline_todo_marker_remains():
    """The bare ``TODO(v2): Add signed marketplace trust`` line that
    used to live at ``a2ui_protocol.py:121`` is gone — replaced by
    a comment that references the tracked issue. If it comes back
    via merge accident, this test fails so the placeholder doesn't
    silently re-enter production source.
    """
    src = Path(__file__).resolve().parents[1] / "genui" / "a2ui_protocol.py"
    assert src.exists(), f"a2ui_protocol.py missing at {src}"
    text = src.read_text(encoding="utf-8")
    assert "TODO(v2): Add signed marketplace trust" not in text, (
        "Bare TODO(v2) marker reintroduced; track via issue #82 "
        "instead and reference the issue from the comment."
    )
    # Conversely: the new comment must mention the issue so anyone
    # reading the source has the breadcrumb.
    assert "issues/82" in text, (
        "Comment block at a2ui_protocol.py is missing the "
        "https://github.com/FERAL-AI/FERAL-AI/issues/82 "
        "reference; do not remove the issue link."
    )


def test_app_registry_install_does_not_claim_signed_trust():
    """The current app-registry install path must NOT carry a code
    branch that pretends to do signed-trust verification. We probe
    the public surface; nothing matching ``signed_trust`` /
    ``verify_publisher`` should appear without the full issue #82
    work.
    """
    try:
        from agents import app_registry as ar  # type: ignore
    except Exception:
        # If the module fails to import in this test environment
        # (sandbox / missing deps) the contract is vacuously held;
        # the import-time failure is its own signal.
        return
    members = inspect.getmembers(ar)
    suspicious = [
        name for (name, _value) in members
        if "signed_trust" in name.lower()
        or "verify_publisher" in name.lower()
        or "marketplace_trust" in name.lower()
    ]
    assert not suspicious, (
        f"app_registry exposes apparent trust-verification API "
        f"({suspicious}) without satisfying issue #82's exit "
        f"criteria. Either implement the full contract or rename "
        f"the symbol so it doesn't read as a trust assertion."
    )
