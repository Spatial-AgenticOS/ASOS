"""Mint an admin publisher token on a live registry instance.

Run inside the Fly container (or any machine where the app is
installed and ``JWT_SECRET`` is set):

    python -m scripts.mint_admin_token --login feral

This does three things:

1. Ensures a row exists in the ``publishers`` table for ``<login>``.
2. Issues a 30-day publisher JWT (HS256) signed with ``JWT_SECRET``.
3. Prints the token to stdout.

This is intentionally a stand-alone management command — it bypasses
the GitHub OAuth flow (which requires a real GitHub user) so operators
can seed the registry before any human has logged in. Keep the token
private; rotate ``JWT_SECRET`` to invalidate all tokens.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from feral_registry.auth import issue_publisher_token  # noqa: E402
from feral_registry.config import get_settings  # noqa: E402
from feral_registry.db import Base, SessionLocal, engine  # noqa: E402
from feral_registry.models import Publisher  # noqa: E402


async def _ensure_publisher(login: str, github_id: int) -> Publisher:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        row = await session.execute(select(Publisher).where(Publisher.github_login == login))
        pub = row.scalar_one_or_none()
        if pub is not None:
            return pub
        pub = Publisher(github_login=login, github_id=github_id)
        session.add(pub)
        await session.commit()
        await session.refresh(pub)
        return pub


async def _main(login: str, github_id: int) -> None:
    settings = get_settings()
    await _ensure_publisher(login, github_id)
    token, ttl = issue_publisher_token(login, settings)
    print(token)
    print(f"# expires in {ttl} seconds", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", default="feral")
    ap.add_argument("--github-id", type=int, default=1, help="placeholder GitHub id for first-party seed publisher")
    args = ap.parse_args()
    asyncio.run(_main(args.login, args.github_id))
