"""
FERAL publish subcommand
========================

Trust model
-----------
Publishers own an Ed25519 keypair stored at ``~/.feral/publisher.key``.
When a bundle is published:

1. The CLI tarballs the source directory (respecting ``.feralignore``).
2. It computes the SHA-256 of the tarball and signs that hash with the
   publisher's private key (detached signature, base64 encoded).
3. The tarball, signature, and manifest JSON are uploaded to the
   registry (``${FERAL_REGISTRY_URL}/api/v1/publish``) as multipart
   form-data.
4. Authentication to the registry is a bearer token obtained via
   ``feral publisher login`` and cached at ``~/.feral/publisher.token``.
5. The publisher's Ed25519 *public* key must be registered with the
   registry (``feral publisher register``) so that installers can later
   verify signatures without trusting the transport alone.

Installers (see ``cli.install``) re-verify the SHA-256 and the detached
signature against the registered public key before extracting anything
to disk.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tarfile
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    from nacl.signing import SigningKey, VerifyKey  # type: ignore
    from nacl.encoding import HexEncoder  # type: ignore
    _NACL_AVAILABLE = True
except ImportError:
    SigningKey = None  # type: ignore
    VerifyKey = None  # type: ignore
    HexEncoder = None  # type: ignore
    _NACL_AVAILABLE = False


DEFAULT_REGISTRY_URL = "https://registry.feral.sh"
# Fallback host that has BOTH A (IPv4) and AAAA (IPv6) records, used when
# the canonical hostname can't be resolved (e.g. networks without IPv6
# connectivity hitting our IPv6-only Fly anycast). The Fly app itself is
# what registry.feral.sh proxies to, so the response shape is identical.
DEFAULT_REGISTRY_FALLBACK_URLS = ("https://feral-registry.fly.dev",)
_HTTP_TIMEOUT = 30.0


def _feral_home() -> Path:
    env = os.environ.get("FERAL_HOME")
    if env:
        return Path(env)
    return Path.home() / ".feral"


def _publisher_key_path() -> Path:
    return _feral_home() / "publisher.key"


def _publisher_token_path() -> Path:
    return _feral_home() / "publisher.token"


def _config_path() -> Path:
    return _feral_home() / "config.yaml"


def registry_base_url(cli_override: Optional[str] = None) -> str:
    """Resolve the registry base URL with the documented precedence.

    Order: ``--registry`` flag > ``FERAL_REGISTRY_URL`` env var >
    ``~/.feral/config.yaml`` ``registry_url`` > default
    ``https://registry.feral.sh``.
    """
    return registry_base_urls(cli_override)[0]


def registry_base_urls(cli_override: Optional[str] = None) -> list[str]:
    """Return the ordered list of registry URLs to try.

    The first entry is the primary URL (same precedence as
    :func:`registry_base_url`). When the primary is the canonical
    public host and no override is in place, we additionally append
    fallback URLs (e.g. the direct Fly app URL) so callers on
    networks with broken IPv6 still reach the registry. Honors the
    env var ``FERAL_REGISTRY_FALLBACK_URLS`` (comma-separated) if you
    want to override the fallback list.
    """
    primary: Optional[str] = None
    if cli_override:
        primary = cli_override.rstrip("/")
    else:
        env_url = os.environ.get("FERAL_REGISTRY_URL", "").strip()
        if env_url:
            primary = env_url.rstrip("/")
        else:
            cfg = _config_path()
            if cfg.exists():
                try:
                    import yaml  # type: ignore

                    data = yaml.safe_load(cfg.read_text()) or {}
                    if isinstance(data, dict) and data.get("registry_url"):
                        primary = str(data["registry_url"]).rstrip("/")
                except Exception:
                    pass
    if primary is None:
        primary = DEFAULT_REGISTRY_URL

    # Build the fallback list. Operators can override with an env var;
    # by default we only attach the canonical fallbacks when the user
    # is talking to the canonical primary (so a custom self-hosted
    # registry never accidentally falls back to feral.sh's Fly app).
    env_fallbacks = os.environ.get("FERAL_REGISTRY_FALLBACK_URLS", "").strip()
    if env_fallbacks:
        fallbacks = [
            u.strip().rstrip("/")
            for u in env_fallbacks.split(",")
            if u.strip()
        ]
    elif primary == DEFAULT_REGISTRY_URL:
        fallbacks = list(DEFAULT_REGISTRY_FALLBACK_URLS)
    else:
        fallbacks = []

    seen: set[str] = set()
    ordered: list[str] = []
    for url in [primary, *fallbacks]:
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _require_nacl() -> None:
    if not _NACL_AVAILABLE:
        print("  pynacl is required for publish/install. Install: pip install pynacl")
        sys.exit(1)


def _require_httpx() -> None:
    if httpx is None:
        print("  httpx is required for publish/install. Install: pip install httpx")
        sys.exit(1)


def load_or_create_signing_key(verbose: bool = True) -> "SigningKey":
    """Load the Ed25519 signing key, creating it on first use."""
    _require_nacl()
    key_path = _publisher_key_path()
    if key_path.exists():
        try:
            raw = key_path.read_text().strip()
            return SigningKey(raw, encoder=HexEncoder)
        except Exception as exc:
            print(f"  Failed to read publisher key at {key_path}: {exc}")
            sys.exit(1)

    key_path.parent.mkdir(parents=True, exist_ok=True)
    sk = SigningKey.generate()
    key_path.write_text(sk.encode(encoder=HexEncoder).decode("ascii"))
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass

    pub_hex = sk.verify_key.encode(encoder=HexEncoder).decode("ascii")
    if verbose:
        print("  Generated a new publisher keypair.")
        print(f"  Private key: {key_path}  (chmod 0600)")
        print(f"  Public key (hex): {pub_hex}")
        print("  Next: run 'feral publisher register' to upload the public key.")
    return sk


def _load_token_or_exit() -> str:
    path = _publisher_token_path()
    if not path.exists():
        print("  No publisher token found. Run 'feral publisher login' first.")
        sys.exit(1)
    token = path.read_text().strip()
    if not token:
        print("  ~/.feral/publisher.token is empty. Run 'feral publisher login'.")
        sys.exit(1)
    return token


# ─────────────────────────────────────────────
# .feralignore handling
# ─────────────────────────────────────────────

def _load_ignore_patterns(source: Path) -> list[str]:
    ignore_file = source / ".feralignore"
    if not ignore_file.exists():
        return []
    patterns: list[str] = []
    for line in ignore_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Very small fnmatch-style ignore matcher.

    Supports plain paths, ``*.ext`` globs, and directory prefixes.
    Intentionally simple — mirrors behaviour publishers expect from
    common ``.gitignore``-like files without pulling in a dependency.
    """
    import fnmatch

    if not patterns:
        return False
    for pat in patterns:
        pat = pat.rstrip("/")
        if fnmatch.fnmatch(rel_path, pat):
            return True
        # directory prefix match
        if rel_path == pat or rel_path.startswith(pat + "/"):
            return True
        # glob against basename
        if fnmatch.fnmatch(os.path.basename(rel_path), pat):
            return True
    return False


def _build_tarball(source: Path, name: str, version: str) -> Path:
    """Tar+gzip the source directory into a temp file. Returns its path."""
    patterns = _load_ignore_patterns(source)
    # Always ignore the ignore file itself and common noise.
    patterns.extend([".feralignore", ".git", ".DS_Store", "__pycache__", "*.pyc"])

    tmp_dir = Path(tempfile.mkdtemp(prefix="feral-publish-"))
    out_path = tmp_dir / f"{name}-{version}.tar.gz"

    source = source.resolve()
    with tarfile.open(out_path, "w:gz") as tar:
        for root, dirs, files in os.walk(source):
            # Prune ignored dirs in-place so os.walk skips them.
            rel_root = os.path.relpath(root, source)
            if rel_root == ".":
                rel_root = ""
            dirs[:] = [
                d for d in dirs
                if not _is_ignored(os.path.join(rel_root, d) if rel_root else d, patterns)
            ]
            for fname in files:
                rel = os.path.join(rel_root, fname) if rel_root else fname
                if _is_ignored(rel, patterns):
                    continue
                abs_path = os.path.join(root, fname)
                tar.add(abs_path, arcname=rel)
    return out_path


def _sha256_file(path: Path) -> bytes:
    h = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.digest()


# ─────────────────────────────────────────────
# Manifest validation
# ─────────────────────────────────────────────

def _validate_skill_manifest(data: dict) -> dict:
    try:
        from models.skill_manifest import SkillManifest

        manifest = SkillManifest(**data)
        return manifest.model_dump(mode="json")
    except Exception as exc:
        print(f"  Skill manifest failed validation: {exc}")
        sys.exit(1)


def _validate_daemon_manifest(data: dict) -> dict:
    try:
        from models.daemon_manifest import DaemonManifest

        manifest = DaemonManifest(**data)
        return manifest.model_dump(mode="json")
    except Exception as exc:
        print(f"  Daemon manifest failed validation: {exc}")
        sys.exit(1)


def _read_manifest(directory: Path) -> dict:
    mf_path = directory / "manifest.json"
    if not mf_path.exists():
        print(f"  manifest.json not found in {directory}")
        sys.exit(1)
    try:
        return json.loads(mf_path.read_text())
    except json.JSONDecodeError as exc:
        print(f"  manifest.json is not valid JSON: {exc}")
        sys.exit(1)


# ─────────────────────────────────────────────
# Publish flow
# ─────────────────────────────────────────────

def cmd_publish(
    skill_dir: Optional[str] = None,
    daemon_dir: Optional[str] = None,
    registry: Optional[str] = None,
) -> None:
    """Publish a skill or daemon bundle to the FERAL registry."""
    if bool(skill_dir) == bool(daemon_dir):
        print("  Specify exactly one of --skill <dir> or --daemon <dir>.")
        sys.exit(2)

    _require_nacl()
    _require_httpx()

    kind = "skill" if skill_dir else "daemon"
    source = Path(skill_dir or daemon_dir).expanduser().resolve()
    if not source.is_dir():
        print(f"  Not a directory: {source}")
        sys.exit(1)

    raw_manifest = _read_manifest(source)
    if kind == "skill":
        manifest = _validate_skill_manifest(raw_manifest)
        name = manifest.get("skill_id") or manifest.get("brand", {}).get("name") or "skill"
        version = manifest.get("version", "0.0.0")
    else:
        manifest = _validate_daemon_manifest(raw_manifest)
        name = manifest.get("id", "daemon")
        version = manifest.get("version", "0.0.0")

    token = _load_token_or_exit()
    signing_key = load_or_create_signing_key(verbose=False)

    print(f"  Packaging {kind} '{name}' v{version} from {source}...")
    tarball = _build_tarball(source, str(name), str(version))
    digest = _sha256_file(tarball)
    signature = signing_key.sign(digest).signature
    sig_b64 = base64.b64encode(signature).decode("ascii")

    base = registry_base_url(registry)
    url = f"{base}/api/v1/publish"
    print(f"  Uploading to {url} ({tarball.stat().st_size} bytes)...")

    try:
        with open(tarball, "rb") as fp:
            files = {"bundle": (tarball.name, fp, "application/gzip")}
            data = {
                "signature": sig_b64,
                "manifest_json": json.dumps(manifest),
                "kind": kind,
                "sha256": digest.hex(),
            }
            headers = {"Authorization": f"Bearer {token}"}
            resp = httpx.post(url, files=files, data=data, headers=headers, timeout=_HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        print(f"  Upload failed: {exc}")
        sys.exit(1)

    if resp.status_code >= 400:
        detail = resp.text[:500]
        print(f"  Registry rejected publish ({resp.status_code}): {detail}")
        sys.exit(1)

    try:
        body = resp.json()
    except Exception:
        body = {}
    item_id = body.get("item_id") or body.get("id") or "<unknown>"
    print(f"  Published! Registry item id: {item_id}")
    print(f"  Install with: feral install {item_id}")


# ─────────────────────────────────────────────
# Publisher auth subcommands
# ─────────────────────────────────────────────

def cmd_publisher_login(registry: Optional[str] = None) -> None:
    """Interactive login flow that stores a bearer token locally."""
    base = registry_base_url(registry)
    login_url = f"{base}/api/v1/auth/github/login"
    print("  FERAL publisher login")
    print(f"  1. Open: {login_url}")
    print("  2. Complete GitHub OAuth — the page will show a 'publisher_token'.")
    print("  3. Paste it below.\n")
    try:
        token = input("  publisher_token> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        sys.exit(1)
    if not token:
        print("  Empty token, aborting.")
        sys.exit(1)
    path = _publisher_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    print(f"  Saved token to {path}")


def cmd_publisher_register(registry: Optional[str] = None) -> None:
    """Register the local Ed25519 public key with the registry."""
    _require_nacl()
    _require_httpx()

    sk = load_or_create_signing_key(verbose=True)
    pub_hex = sk.verify_key.encode(encoder=HexEncoder).decode("ascii")
    token = _load_token_or_exit()

    base = registry_base_url(registry)
    url = f"{base}/api/v1/auth/github/register_pubkey"

    try:
        resp = httpx.post(
            url,
            json={"pubkey_hex": pub_hex},
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        print(f"  Registration failed: {exc}")
        sys.exit(1)

    if resp.status_code >= 400:
        print(f"  Registry rejected registration ({resp.status_code}): {resp.text[:500]}")
        sys.exit(1)
    print(f"  Registered public key with {base}.")
    print(f"  Public key (hex): {pub_hex}")
