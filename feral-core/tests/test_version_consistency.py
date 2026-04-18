"""Fail CI if any hard-coded FERAL version string drifts out of sync.

We load ``scripts/bump_version.py`` by path (it lives outside the
``feral-core/`` package and is not importable via normal ``import``) and
re-use its declarative ``VERSION_LOCATIONS`` list as the single source of
truth. Every file that exists is expected to expose the SAME version
string via its regex.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ASOS_ROOT = Path(__file__).resolve().parents[2]
BUMP_SCRIPT = ASOS_ROOT / "scripts" / "bump_version.py"


def _load_bump_module():
    spec = importlib.util.spec_from_file_location(
        "feral_bump_version", BUMP_SCRIPT
    )
    assert spec and spec.loader, f"cannot load bump script at {BUMP_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bump_module():
    if not BUMP_SCRIPT.exists():
        pytest.skip(f"{BUMP_SCRIPT} not present in this checkout")
    return _load_bump_module()


def _extract_versions(module) -> dict[str, set[str]]:
    """For every declared location that exists, return {relpath: {versions}}."""
    observed: dict[str, set[str]] = {}
    for loc in module.VERSION_LOCATIONS:
        abs_path = module.ASOS_ROOT / loc.path
        if not abs_path.exists():
            continue
        text = abs_path.read_text(encoding="utf-8")
        versions = {m.group("version") for m in loc.pattern.finditer(text)}
        if versions:
            observed[loc.path] = versions
    return observed


def test_version_locations_declared(bump_module):
    assert bump_module.VERSION_LOCATIONS, "no version locations declared"
    for loc in bump_module.VERSION_LOCATIONS:
        assert "version" in loc.pattern.groupindex, (
            f"location for {loc.path} is missing a named 'version' capture group"
        )


def test_single_calver_across_all_files(bump_module):
    observed = _extract_versions(bump_module)
    assert observed, "no declared version files were found on disk"

    all_versions: set[str] = set()
    for versions in observed.values():
        all_versions.update(versions)

    if len(all_versions) != 1:
        per_file = "\n".join(
            f"    {path}: {sorted(v)}" for path, v in sorted(observed.items())
        )
        raise AssertionError(
            "FERAL version strings have drifted across files. "
            "Run `python3 scripts/bump_version.py <version>` to resync.\n"
            f"Distinct versions found: {sorted(all_versions)}\n"
            f"Per-file breakdown:\n{per_file}"
        )


def test_calver_shape(bump_module):
    observed = _extract_versions(bump_module)
    versions = {v for values in observed.values() for v in values}
    for v in versions:
        assert bump_module.CALVER_RE.match(v), (
            f"version {v!r} does not look like YYYY.M.D"
        )
