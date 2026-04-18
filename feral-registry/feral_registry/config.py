"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_url: str = Field(
        default="sqlite+aiosqlite:///./registry.db",
        alias="FERAL_REGISTRY_DB_URL",
    )
    blob_dir: Path = Field(default=Path("./_blobs"), alias="FERAL_REGISTRY_BLOB_DIR")

    github_client_id: str | None = Field(default=None, alias="GITHUB_CLIENT_ID")
    github_client_secret: str | None = Field(default=None, alias="GITHUB_CLIENT_SECRET")
    github_redirect_uri: str = Field(
        default="http://localhost:8080/api/v1/auth/github/callback",
        alias="GITHUB_REDIRECT_URI",
    )

    jwt_secret: str = Field(default="dev-insecure-change-me", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_ttl_days: int = 30

    featured_publishers_raw: str = Field(default="", alias="FEATURED_PUBLISHERS")

    public_base_url: str = Field(
        default="http://localhost:8080", alias="FERAL_REGISTRY_PUBLIC_URL"
    )

    @property
    def featured_publishers(self) -> List[str]:
        return [
            h.strip().lower()
            for h in self.featured_publishers_raw.split(",")
            if h.strip()
        ]

    @property
    def github_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.blob_dir.mkdir(parents=True, exist_ok=True)
    return s
