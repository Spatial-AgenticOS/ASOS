"""Seed the registry with first-party Feral skills and daemons.

This script is intended to be run **manually on the deployed instance** after
its first boot:

    fly ssh console -C "python -m scripts.seed_first_party"

It reads manifests from ``ASOS/feral-core/skills/manifests/*.json``, builds a
tarball containing the manifest plus the matching implementation module from
``ASOS/feral-core/skills/impl/``, signs each tarball with a deterministic
"first_party" seed key, and inserts them as verified items under the ``feral``
publisher. It also looks for ``ASOS/feral-nodes/w300_daemon/`` and
``ASOS/feral-nodes/wristband_daemon/`` directories and seeds them as daemon
entries with manifest inferred from ``manifest.json`` / ``daemon.json`` if
present.

The script is idempotent: `(kind, name, version)` tuples already in the
database are skipped.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

from nacl.signing import SigningKey
from sqlalchemy import select

# Allow running as `python scripts/seed_first_party.py` from the package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from feral_registry.config import get_settings  # noqa: E402
from feral_registry.db import Base, SessionLocal, engine  # noqa: E402
from feral_registry.models import Item, Publisher  # noqa: E402

FIRST_PARTY_LOGIN = "feral"
FIRST_PARTY_GH_ID = 1
SEED_KEY_ENV = "FERAL_REGISTRY_SEED_KEY_HEX"


@dataclass
class SeedItem:
    kind: str  # skill | daemon | mcp
    name: str
    version: str
    manifest: dict
    files: list[tuple[str, bytes]]  # (arcname, bytes)


def _repo_root() -> Path:
    # Resolve ASOS/ relative to this script.
    return Path(__file__).resolve().parents[2]


def _load_skill_seeds() -> list[SeedItem]:
    root = _repo_root() / "feral-core" / "skills"
    manifests_dir = root / "manifests"
    impl_dir = root / "impl"
    seeds: list[SeedItem] = []
    if not manifests_dir.exists():
        return seeds
    for manifest_path in sorted(manifests_dir.glob("*.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            continue
        name = manifest.get("skill_id") or manifest.get("name") or manifest_path.stem
        version = str(manifest.get("version", "0.1.0"))
        files: list[tuple[str, bytes]] = [
            (f"manifests/{manifest_path.name}", manifest_path.read_bytes()),
        ]
        impl_py = impl_dir / f"{manifest_path.stem}.py"
        if impl_py.exists():
            files.append((f"impl/{impl_py.name}", impl_py.read_bytes()))
        seeds.append(
            SeedItem(
                kind="skill",
                name=name,
                version=version,
                manifest={
                    "kind": "skill",
                    "name": name,
                    "version": version,
                    "description": manifest.get("description"),
                    "author": manifest.get("author", "feral-core"),
                    "original": manifest,
                },
                files=files,
            )
        )
    return seeds


def _load_daemon_seeds() -> list[SeedItem]:
    nodes_root = _repo_root() / "feral-nodes"
    seeds: list[SeedItem] = []
    for dirname in ("w300_daemon", "wristband_daemon"):
        daemon_dir = nodes_root / dirname
        if not daemon_dir.exists():
            continue
        manifest_file = None
        for cand in ("manifest.json", "daemon.json", "package.json"):
            if (daemon_dir / cand).exists():
                manifest_file = daemon_dir / cand
                break
        raw_manifest: dict = {}
        if manifest_file:
            try:
                raw_manifest = json.loads(manifest_file.read_text())
            except json.JSONDecodeError:
                raw_manifest = {}
        name = raw_manifest.get("name", dirname)
        version = str(raw_manifest.get("version", "0.1.0"))
        files: list[tuple[str, bytes]] = []
        for p in sorted(daemon_dir.rglob("*")):
            if p.is_file() and p.stat().st_size < 1_000_000:
                rel = p.relative_to(daemon_dir)
                files.append((str(rel), p.read_bytes()))
        seeds.append(
            SeedItem(
                kind="daemon",
                name=name,
                version=version,
                manifest={
                    "kind": "daemon",
                    "name": name,
                    "version": version,
                    "description": raw_manifest.get(
                        "description", f"First-party {dirname} daemon."
                    ),
                    "author": "feral-core",
                    "original": raw_manifest,
                },
                files=files,
            )
        )
    return seeds


def _build_tarball(seed: SeedItem) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        manifest_bytes = json.dumps(seed.manifest, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))
        for arcname, data in seed.files:
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _get_seed_signing_key() -> SigningKey:
    hex_key = os.environ.get(SEED_KEY_ENV)
    if hex_key:
        return SigningKey(bytes.fromhex(hex_key))
    # Deterministic dev seed. Override in production via FERAL_REGISTRY_SEED_KEY_HEX.
    return SigningKey(b"feral-first-party-seed-key-32byt")


async def _ensure_first_party_publisher(session, pubkey_hex: str) -> Publisher:
    row = await session.execute(
        select(Publisher).where(Publisher.github_login == FIRST_PARTY_LOGIN)
    )
    pub = row.scalar_one_or_none()
    if pub is None:
        pub = Publisher(
            github_login=FIRST_PARTY_LOGIN,
            github_id=FIRST_PARTY_GH_ID,
            pubkey_hex=pubkey_hex,
        )
        session.add(pub)
        await session.flush()
    else:
        pub.pubkey_hex = pubkey_hex
    return pub


async def seed() -> int:
    settings = get_settings()
    settings.blob_dir.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sk = _get_seed_signing_key()
    pubkey_hex = sk.verify_key.encode().hex()

    seeds = _load_skill_seeds() + _load_daemon_seeds()
    inserted = 0

    async with SessionLocal() as session:
        pub = await _ensure_first_party_publisher(session, pubkey_hex)

        for seed_item in seeds:
            existing = await session.execute(
                select(Item.id).where(
                    Item.kind == seed_item.kind,
                    Item.name == seed_item.name,
                    Item.version == seed_item.version,
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            bundle = _build_tarball(seed_item)
            sha = hashlib.sha256(bundle).hexdigest()
            sig = base64.b64encode(sk.sign(sha.encode("ascii")).signature).decode("ascii")
            blob_path = settings.blob_dir / f"{sha}.tar.gz"
            blob_path.write_bytes(bundle)

            session.add(
                Item(
                    kind=seed_item.kind,
                    name=seed_item.name,
                    version=seed_item.version,
                    author_id=pub.id,
                    manifest_json=json.dumps(seed_item.manifest, sort_keys=True),
                    sha256=sha,
                    blob_path=str(blob_path),
                    size_bytes=len(bundle),
                    signature_b64=sig,
                    verified=True,
                )
            )
            inserted += 1

        await session.commit()

    print(f"Seeded {inserted} first-party item(s). Publisher pubkey: {pubkey_hex}")
    return inserted


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
