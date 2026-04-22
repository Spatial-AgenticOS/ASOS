"""
feral app CLI — scaffold, validate, build, install, publish a GenUI app.

Subcommands
-----------
* ``feral app init <name>``     — scaffold manifest.yaml + surfaces/ +
                                  interactions.yaml + brand/logo.svg +
                                  README.md under ``./<name>/``.
* ``feral app validate <dir>``  — parse the manifest via AppManifest and
                                  re-run every validator (cross-refs,
                                  action contracts, schemas).
* ``feral app build <dir>``     — produce a reproducible tarball under
                                  ``<dir>/dist/<app_id>-<version>.tar.gz``.
* ``feral app install <path>``  — POST /api/apps/install {path: ...} so
                                  the running brain loads the app into
                                  AppRegistry.
* ``feral app publish <dir>``   — sign the tarball with the publisher's
                                  Ed25519 key and POST to
                                  registry.feral.sh/api/v1/publish with
                                  kind=app.

Shares the signing + tokening infrastructure already in
``feral-core/cli/publish.py`` so publishers don't need a second keypair.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tarfile
import textwrap
from hashlib import sha256
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:  # pragma: no cover — optional for offline subcommands
    httpx = None  # type: ignore


def _print(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------
# init
# ---------------------------------------------------------------------


_SCAFFOLD_MANIFEST = """\
app_id: {app_id}
version: 0.1.0
author: your-github-handle
description: A GenUI app built on FERAL.

brand:
  name: {title}
  primary_color: "#5B21B6"
  secondary_color: "#A78BFA"

permissions: []

data_schemas:
  - schema_id: home_data
    schema:
      type: object
      properties:
        greeting:
          type: string

entry_surface_id: home

surfaces:
  - surface_id: home
    title: Home
    kind: authored
    data_schema_ref: home_data
    template_root:
      type: VStack
      spacing: md
      padding: md
      children:
        - type: Text
          value: "$data.greeting"
          style: headline
        - type: Button
          label: "Tap me"
          action_id: hello
          style: primary
    action_contract:
      - action_id: hello
        handler: app_event
        description: Primary call to action.

interactions:
  button_style_priority: ["primary", "secondary", "ghost"]
  destructive_confirmation_required: true
  list_render_preference: auto
  accessibility_notes:
    - "Respect the user's color-contrast preference."
  prose_guidance: |
    Never show raw IDs. Localise timestamps. Use brand primary for
    affirmative actions only.
"""

_SCAFFOLD_README = """\
# {title}

A FERAL GenUI app.

## Build + install locally

    feral app validate ./
    feral app install ./

## Publish

    feral publisher login
    feral app publish ./

## Structure

    manifest.yaml         # AppManifest — brand + schemas + surfaces + rules
    surfaces/             # (optional) split large templates into files referenced
                          # from manifest.yaml via relative paths.
    brand/                # logo, screenshots, etc. — shipped with the bundle.
"""


def cmd_app_init(name: str) -> None:
    slug = _slugify(name)
    if not slug:
        _print("  App name must contain at least 3 letters or digits.")
        sys.exit(2)
    dest = Path(slug).resolve()
    if dest.exists():
        _print(f"  {dest} already exists; pick another name or remove it first.")
        sys.exit(2)
    dest.mkdir(parents=True)
    (dest / "surfaces").mkdir()
    (dest / "brand").mkdir()
    manifest_text = _SCAFFOLD_MANIFEST.format(app_id=slug, title=name.title())
    (dest / "manifest.yaml").write_text(manifest_text)
    (dest / "README.md").write_text(_SCAFFOLD_README.format(title=name.title()))
    (dest / ".feralignore").write_text("dist/\nnode_modules/\n__pycache__/\n")
    _print(f"  Scaffolded FERAL app at {dest}")
    _print("  Edit manifest.yaml, then: feral app validate ./ && feral app install ./")


def _slugify(name: str) -> str:
    cleaned = []
    for ch in name.strip().lower():
        if ch.isalnum():
            cleaned.append(ch)
        elif ch in ("-", "_", " "):
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")
    # Collapse repeat dashes
    while "--" in slug:
        slug = slug.replace("--", "-")
    # Must start with a letter
    while slug and not slug[0].isalpha():
        slug = slug[1:]
    return slug[:64]


# ---------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------


def cmd_app_validate(path: str) -> None:
    source = Path(path).expanduser().resolve()
    if not source.is_dir():
        _print(f"  Not a directory: {source}")
        sys.exit(2)
    try:
        manifest = _load_manifest(source)
    except Exception as exc:
        _print(f"  Manifest failed to load: {exc}")
        sys.exit(1)
    try:
        from models.app_manifest import AppManifest
    except Exception as exc:
        _print(f"  AppManifest model unavailable in this install: {exc}")
        sys.exit(1)
    try:
        model = AppManifest(**manifest)
    except Exception as exc:
        _print(f"  Manifest validation failed: {exc}")
        sys.exit(1)
    _print(f"  OK. {model.app_id} v{model.version} — {len(model.surfaces)} surface(s).")
    _print(f"  Entry surface: {model.entry_surface_id}")
    for s in model.surfaces:
        _print(
            f"    - {s.surface_id} (kind={s.kind}, actions={len(s.action_contract)})"
        )


# ---------------------------------------------------------------------
# build
# ---------------------------------------------------------------------


def cmd_app_build(path: str, out: Optional[str] = None) -> None:
    source = Path(path).expanduser().resolve()
    if not source.is_dir():
        _print(f"  Not a directory: {source}")
        sys.exit(2)
    try:
        manifest = _load_manifest(source)
        from models.app_manifest import AppManifest
        model = AppManifest(**manifest)
    except Exception as exc:
        _print(f"  Can't build — manifest invalid: {exc}")
        sys.exit(1)
    out_path = Path(out) if out else source / "dist" / f"{model.app_id}-{model.version}.tar.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    patterns = _load_ignore_patterns(source)
    size = _build_tarball(source, out_path, patterns)
    _print(f"  Built {out_path} ({size} bytes).")


def _build_tarball(source: Path, out_path: Path, patterns: list[str]) -> int:
    if out_path.exists():
        out_path.unlink()
    with tarfile.open(out_path, "w:gz") as tar:
        for root, dirs, files in os.walk(source):
            # Respect .feralignore
            rel_root = Path(root).relative_to(source)
            if _is_ignored(str(rel_root), patterns):
                dirs[:] = []
                continue
            for fname in files:
                rel = (rel_root / fname).as_posix()
                if _is_ignored(rel, patterns):
                    continue
                full = Path(root) / fname
                tar.add(full, arcname=rel)
    return out_path.stat().st_size


def _load_ignore_patterns(source: Path) -> list[str]:
    patterns: list[str] = []
    path = source / ".feralignore"
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line.rstrip("/"))
    return patterns


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    if not rel_path or rel_path == ".":
        return False
    for pattern in patterns:
        if rel_path == pattern or rel_path.startswith(pattern.rstrip("/") + "/"):
            return True
    return False


# ---------------------------------------------------------------------
# install (local)
# ---------------------------------------------------------------------


def cmd_app_install(path: str, host: Optional[str] = None, port: Optional[str] = None) -> None:
    if httpx is None:
        _print("  httpx is required for `feral app install`. Install feral-ai[cli].")
        sys.exit(1)
    source = Path(path).expanduser().resolve()
    if not source.is_dir():
        _print(f"  Not a directory: {source}")
        sys.exit(2)
    base = _brain_base_url(host, port)
    url = f"{base.rstrip('/')}/api/apps/install"
    body = {"path": str(source), "overwrite": True}
    try:
        resp = httpx.post(url, json=body, timeout=30.0)
    except httpx.HTTPError as exc:
        _print(f"  Could not reach brain at {url}: {exc}")
        sys.exit(1)
    if resp.status_code >= 400:
        _print(f"  Install rejected ({resp.status_code}): {resp.text[:400]}")
        sys.exit(1)
    try:
        data = resp.json()
    except Exception:
        data = {}
    app = data.get("app") or {}
    _print(f"  Installed {app.get('app_id', '<unknown>')} v{app.get('version', '?')}.")


# ---------------------------------------------------------------------
# publish (signed network)
# ---------------------------------------------------------------------


def cmd_app_publish(path: str, registry: Optional[str] = None) -> None:
    if httpx is None:
        _print("  httpx is required for `feral app publish`. Install feral-ai[cli].")
        sys.exit(1)
    try:
        from cli.publish import (
            _load_token_or_exit,
            _sha256_file,
            load_or_create_signing_key,
            registry_base_url,
        )
    except Exception as exc:
        _print(f"  Publisher tooling unavailable: {exc}")
        sys.exit(1)

    source = Path(path).expanduser().resolve()
    if not source.is_dir():
        _print(f"  Not a directory: {source}")
        sys.exit(2)

    try:
        manifest = _load_manifest(source)
        from models.app_manifest import AppManifest
        model = AppManifest(**manifest)
    except Exception as exc:
        _print(f"  Manifest invalid: {exc}")
        sys.exit(1)

    # Registry's Manifest model expects top-level kind/name/version in
    # addition to the app-specific fields. Wrap the AppManifest dump
    # inside that envelope so the registry's validator is happy.
    registry_manifest = {
        "kind": "app",
        "name": model.app_id,
        "version": model.version,
        "description": model.description,
        "author": model.author,
        "app_id": model.app_id,
        "brand": model.brand.model_dump(),
        "entry_surface_id": model.entry_surface_id,
        "surfaces": [s.model_dump() for s in model.surfaces],
    }

    dist_dir = source / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    out_path = dist_dir / f"{model.app_id}-{model.version}.tar.gz"
    patterns = _load_ignore_patterns(source)
    _build_tarball(source, out_path, patterns)

    token = _load_token_or_exit()
    signing_key = load_or_create_signing_key(verbose=False)

    digest = _sha256_file(out_path)
    signature = signing_key.sign(digest).signature
    sig_b64 = base64.b64encode(signature).decode("ascii")

    base = registry_base_url(registry)
    url = f"{base}/api/v1/publish"
    _print(f"  Uploading app '{model.app_id}' v{model.version} to {url}...")

    with open(out_path, "rb") as fp:
        files = {"bundle": (out_path.name, fp, "application/gzip")}
        data = {
            "signature": sig_b64,
            "manifest_json": json.dumps(registry_manifest),
        }
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = httpx.post(url, files=files, data=data, headers=headers, timeout=30.0)
        except httpx.HTTPError as exc:
            _print(f"  Upload failed: {exc}")
            sys.exit(1)

    if resp.status_code >= 400:
        _print(f"  Registry rejected publish ({resp.status_code}): {resp.text[:400]}")
        sys.exit(1)
    try:
        body = resp.json()
    except Exception:
        body = {}
    _print(f"  Published! item_id: {body.get('id', '<unknown>')}")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _load_manifest(source: Path) -> dict:
    yaml_path = source / "manifest.yaml"
    json_path = source / "manifest.json"
    if yaml_path.exists():
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyyaml required to parse manifest.yaml") from exc
        raw = yaml.safe_load(yaml_path.read_text()) or {}
    elif json_path.exists():
        raw = json.loads(json_path.read_text())
    else:
        raise FileNotFoundError(f"no manifest.yaml or manifest.json in {source}")
    # Inline surface templates referenced as relative file paths, same
    # behaviour as AppRegistry.install_from_dir so `validate` + `build`
    # match install-time semantics.
    surfaces = raw.get("surfaces")
    if isinstance(surfaces, list):
        for surface in surfaces:
            if isinstance(surface, dict):
                template_root = surface.get("template_root")
                if isinstance(template_root, str):
                    candidate = (source / template_root).resolve()
                    if candidate.is_file():
                        surface["template_root"] = json.loads(candidate.read_text())
    return raw


def _brain_base_url(host: Optional[str], port: Optional[str]) -> str:
    if host or port:
        h = host or "localhost"
        p = port or "9090"
        scheme = "https" if p == "443" else "http"
        return f"{scheme}://{h}:{p}"
    env = os.environ.get("FERAL_BRAIN_URL")
    if env:
        return env
    return "http://localhost:9090"


# ---------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------


def register_app_subparser(sub) -> None:
    """Attach `feral app ...` subcommands onto the main argparse registry."""
    app_p = sub.add_parser("app", help="FERAL GenUI app: init / validate / build / install / publish")
    app_sub = app_p.add_subparsers(dest="app_subcommand", required=True)

    init_p = app_sub.add_parser("init", help="Scaffold a new GenUI app folder.")
    init_p.add_argument("name", help="Human name for the app (becomes the slug).")

    val_p = app_sub.add_parser("validate", help="Validate an app bundle folder against the AppManifest schema.")
    val_p.add_argument("path", nargs="?", default=".")

    build_p = app_sub.add_parser("build", help="Produce a reproducible tarball under <path>/dist/.")
    build_p.add_argument("path", nargs="?", default=".")
    build_p.add_argument("--out", default=None)

    inst_p = app_sub.add_parser("install", help="Install a local app bundle into the running brain.")
    inst_p.add_argument("path", nargs="?", default=".")
    inst_p.add_argument("--host", default=None)
    inst_p.add_argument("--port", default=None)

    pub_p = app_sub.add_parser("publish", help="Sign + publish an app bundle to registry.feral.sh.")
    pub_p.add_argument("path", nargs="?", default=".")
    pub_p.add_argument("--registry", default=None)


def dispatch_app_subcommand(args: argparse.Namespace) -> None:
    sub = getattr(args, "app_subcommand", "")
    if sub == "init":
        cmd_app_init(args.name)
    elif sub == "validate":
        cmd_app_validate(args.path)
    elif sub == "build":
        cmd_app_build(args.path, out=args.out)
    elif sub == "install":
        cmd_app_install(args.path, host=args.host, port=args.port)
    elif sub == "publish":
        cmd_app_publish(args.path, registry=args.registry)
    else:
        _print("  Unknown `feral app` subcommand.")
        sys.exit(2)
