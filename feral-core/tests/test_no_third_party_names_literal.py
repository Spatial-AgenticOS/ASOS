"""W24c — pytest sibling of ``scripts/check_no_third_party_names.py``.

This test duplicates the CI gate inside pytest so a local developer
catches a forbidden third-party project name (``openclaw``, etc.)
before pushing a PR and hitting CI.

It loads the scanning library function directly from the repo-root
``scripts/check_no_third_party_names.py`` and asserts the hit list is
empty. The test auto-skips if the linter script is missing (resilient
to partial checkouts).

See ``.cursor/rules/no-third-party-project-names-in-deliverables.mdc``
for the rule the check enforces.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ASOS_ROOT = Path(__file__).resolve().parents[2]
LINTER_PATH = ASOS_ROOT / "scripts" / "check_no_third_party_names.py"


def _load_linter():
    if not LINTER_PATH.exists():
        pytest.skip(
            f"linter script not found at {LINTER_PATH}; run the test "
            "from a full checkout"
        )
    spec = importlib.util.spec_from_file_location(
        "feral_check_no_third_party_names", LINTER_PATH
    )
    if spec is None or spec.loader is None:
        pytest.skip(f"unable to load linter from {LINTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_no_forbidden_third_party_names_in_shipped_artifacts():
    linter = _load_linter()
    hits = linter.scan_repo(ASOS_ROOT)
    if hits:
        formatted = linter.format_hits(hits)
        pytest.fail(
            "Forbidden third-party project name(s) found in shipped "
            "artifacts:\n"
            f"{formatted}\n\n"
            "Fix: rewrite the prose per the 'Replacement vocabulary' "
            "in .cursor/rules/no-third-party-project-names-in-"
            "deliverables.mdc"
        )


def test_forbidden_terms_list_is_nonempty():
    linter = _load_linter()
    assert linter.FORBIDDEN_TERMS, (
        "FORBIDDEN_TERMS must be non-empty; the rule today blocks at "
        "least 'openclaw' (see workspace rule)."
    )
