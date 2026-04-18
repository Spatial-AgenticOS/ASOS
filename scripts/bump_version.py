#!/usr/bin/env python3
"""FERAL version-bump automation.

One place to change every hard-coded version string in the monorepo. CI
also imports ``VERSION_LOCATIONS`` from this module to detect drift
(see ``feral-core/tests/test_version_consistency.py``).

Usage:
    python scripts/bump_version.py 2026.4.9           # rewrite in place
    python scripts/bump_version.py 2026.4.9 --check   # dry run

Every entry in ``VERSION_LOCATIONS`` is a 3-tuple:

    (path_relative_to_ASOS, compiled_regex, replacement_template)

The regex MUST expose a named capture group called ``version`` that
captures exactly the version string (e.g. ``2026.4.16``). The
replacement template uses ``{version}`` for the new value.

Missing declared files emit a WARNING and the script continues — this is
intentional so that partial checkouts (e.g. stripped publish tarballs)
don't blow up CI.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ASOS_ROOT = Path(__file__).resolve().parent.parent

CALVER_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$")

VERSION_PATTERN = r"(?P<version>\d{4}\.\d{1,2}\.\d{1,2})"


@dataclass(frozen=True)
class VersionLocation:
    """A single file × regex × replacement tuple."""

    path: str
    pattern: re.Pattern
    replacement: str
    description: str = ""


def _p(raw: str, flags: int = 0) -> re.Pattern:
    return re.compile(raw, flags)


VERSION_LOCATIONS: tuple[VersionLocation, ...] = (
    VersionLocation(
        path="pyproject.toml",
        pattern=_p(rf'(?m)^version = "{VERSION_PATTERN}"'),
        replacement='version = "{version}"',
        description="[project] version in top-level pyproject.toml",
    ),
    VersionLocation(
        path="feral-core/pyproject.toml",
        pattern=_p(rf'(?m)^version = "{VERSION_PATTERN}"'),
        replacement='version = "{version}"',
        description="[project] version in feral-core pyproject.toml",
    ),
    VersionLocation(
        path="feral-core/version.py",
        pattern=_p(rf'__version__ = "{VERSION_PATTERN}"'),
        replacement='__version__ = "{version}"',
        description="__version__ constant in feral-core/version.py",
    ),
    VersionLocation(
        path="feral-core/services/mdns.py",
        pattern=_p(rf'"version":\s*"{VERSION_PATTERN}"'),
        replacement='"version": "{version}"',
        description='mDNS ServiceInfo properties["version"]',
    ),
    VersionLocation(
        path="feral-core/agents/self_model.py",
        pattern=_p(rf"version={VERSION_PATTERN}"),
        replacement="version={version}",
        description="Runtime: line example in build_runtime_line docstring",
    ),
    VersionLocation(
        path="README.md",
        pattern=_p(rf"badge/version-{VERSION_PATTERN}-"),
        replacement="badge/version-{version}-",
        description="shields.io version badge URL",
    ),
    VersionLocation(
        path="CHANGELOG.md",
        pattern=_p(rf"<!--\s*feral-version:\s*{VERSION_PATTERN}\s*-->"),
        replacement="<!-- feral-version: {version} -->",
        description=(
            "Non-destructive current-version marker at the top of the "
            "changelog. Do NOT point this at historical ## [x.y.z] "
            "section headers."
        ),
    ),
    VersionLocation(
        path="feral-client/src/components/AppShell.jsx",
        pattern=_p(rf"'{VERSION_PATTERN}'"),
        replacement="'{version}'",
        description="AppShell version fallback literals",
    ),
    VersionLocation(
        path="feral-client/src/pages/Dashboard.jsx",
        pattern=_p(rf"'{VERSION_PATTERN}'"),
        replacement="'{version}'",
        description="Dashboard version fallback literal",
    ),
    VersionLocation(
        path="feral-client/src/pages/SetupWizard.jsx",
        pattern=_p(rf"FERAL v{VERSION_PATTERN}"),
        replacement="FERAL v{version}",
        description="Setup wizard footer version",
    ),
    VersionLocation(
        path="feral-extension/manifest.json",
        pattern=_p(rf'"version":\s*"{VERSION_PATTERN}"'),
        replacement='"version": "{version}"',
        description="Chrome extension manifest version",
    ),
    VersionLocation(
        path="feral-extension/popup.html",
        pattern=_p(rf"v{VERSION_PATTERN}"),
        replacement="v{version}",
        description="Popup footer version label",
    ),
    VersionLocation(
        path="feral-ha-addon/config.json",
        pattern=_p(rf'"version":\s*"{VERSION_PATTERN}"'),
        replacement='"version": "{version}"',
        description="HA add-on config.json version",
    ),
    VersionLocation(
        path="feral-ha-addon/config.yaml",
        pattern=_p(rf'(?m)^version:\s*"{VERSION_PATTERN}"'),
        replacement='version: "{version}"',
        description="HA add-on config.yaml version",
    ),
    VersionLocation(
        path="feral-ha-addon/Dockerfile",
        pattern=_p(rf"ARG FERAL_VERSION={VERSION_PATTERN}"),
        replacement="ARG FERAL_VERSION={version}",
        description="HA add-on Dockerfile FERAL_VERSION build arg",
    ),
    VersionLocation(
        path="feral-ha-addon/UPGRADE.md",
        pattern=_p(rf"ARG FERAL_VERSION={VERSION_PATTERN}"),
        replacement="ARG FERAL_VERSION={version}",
        description="UPGRADE.md FERAL_VERSION example (pin code-block)",
    ),
    VersionLocation(
        path=".github/workflows/ha-addon.yml",
        pattern=_p(rf"--build-arg FERAL_VERSION={VERSION_PATTERN}"),
        replacement="--build-arg FERAL_VERSION={version}",
        description="CI workflow FERAL_VERSION build-arg",
    ),
    VersionLocation(
        path="feral-nodes/android-app/build.gradle.kts",
        pattern=_p(rf'versionName\s*=\s*"{VERSION_PATTERN}"'),
        replacement='versionName = "{version}"',
        description="Android app versionName",
    ),
)


class BumpReport:
    __slots__ = ("files_changed", "occurrences", "missing", "not_found")

    def __init__(self) -> None:
        self.files_changed: set[str] = set()
        self.occurrences: int = 0
        self.missing: list[str] = []
        self.not_found: list[str] = []


def _apply(
    text: str, loc: VersionLocation, new_version: str
) -> tuple[str, list[tuple[str, str]]]:
    """Return (new_text, [(old, new), ...]) for each replacement made."""
    replacements: list[tuple[str, str]] = []
    replacement_template = loc.replacement.format(version=new_version)

    def _sub(match: re.Match) -> str:
        old_full = match.group(0)
        old_version = match.group("version")
        if old_version == new_version:
            return old_full
        replacements.append((old_full, replacement_template))
        return replacement_template

    new_text = loc.pattern.sub(_sub, text)
    return new_text, replacements


def bump(new_version: str, *, check: bool = False) -> BumpReport:
    if not CALVER_RE.match(new_version):
        raise SystemExit(
            f"✗ invalid calver '{new_version}' — expected YYYY.M.D or YYYY.MM.DD"
        )

    report = BumpReport()
    for loc in VERSION_LOCATIONS:
        abs_path = ASOS_ROOT / loc.path
        if not abs_path.exists():
            report.missing.append(loc.path)
            print(f"  ⚠ WARNING: declared file not found: {loc.path}")
            continue

        original = abs_path.read_text(encoding="utf-8")
        new_text, replacements = _apply(original, loc, new_version)

        if not replacements:
            if not loc.pattern.search(original):
                report.not_found.append(loc.path)
                print(
                    f"  ⚠ WARNING: pattern did not match anything in {loc.path}"
                    f" ({loc.description})"
                )
            continue

        report.files_changed.add(loc.path)
        report.occurrences += len(replacements)
        mode = "DRY-RUN" if check else "EDIT"
        print(f"  [{mode}] {loc.path}")
        for old_full, new_full in replacements:
            print(f"      - {old_full}")
            print(f"      + {new_full}")

        if not check:
            abs_path.write_text(new_text, encoding="utf-8")

    verb = "would bump" if check else "bumped"
    print(
        f"\n✓ {verb} {report.occurrences} occurrence(s) "
        f"across {len(report.files_changed)} file(s) to {new_version}"
    )
    if report.missing:
        print(f"  ({len(report.missing)} declared file(s) missing; see warnings above)")
    if report.not_found:
        print(
            f"  ({len(report.not_found)} file(s) had no pattern match; "
            "see warnings above)"
        )
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bump_version",
        description="Bump FERAL version strings across the monorepo.",
    )
    parser.add_argument(
        "version",
        help="New calver version, e.g. 2026.4.9",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry run: print what would change without writing files.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    bump(args.version, check=args.check)
    return 0


if __name__ == "__main__":
    sys.exit(main())
