"""PR 10: local-first upload storage.

Why this module
---------------
FERAL has had to fake file attachments for too long: clients PDF-encoded
multipart bodies on one path and the wiki endpoint expected JSON on
another, so nothing actually shipped. This module owns the canonical
upload pipeline:

1. The web composer POSTs a multipart file to ``/api/uploads``.
2. :class:`UploadStore` writes the bytes to
   ``$FERAL_HOME/uploads/<upload_id>``, records metadata in a JSON
   index, and returns an :class:`UploadRecord`.
3. Subsequent commands reference the file by ``upload_id`` via the
   ``attachments`` field on :class:`TextCommandPayload` (model-visible
   without inlining bytes).

Local-first contract
--------------------
* Files never leave the user's machine implicitly. The store is a
  plain on-disk directory under ``$FERAL_HOME``.
* Per-upload quota and total storage quota are *enforced* — the route
  rejects oversize uploads with a 413, not a silent truncation.
* Each record carries a SHA-256 of the bytes so the orchestrator can
  surface "you've sent this file before" honestly.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional
from uuid import uuid4

from config.loader import feral_data_home

logger = logging.getLogger("feral.memory.uploads")


DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024     # 25 MiB per upload
DEFAULT_MAX_TOTAL_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB total store


@dataclass
class UploadRecord:
    upload_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: float
    path: str = ""  # absolute on-disk path
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


class UploadQuotaExceeded(RuntimeError):
    """Raised when a request would push the store over its quota."""


class UploadStore:
    """JSON-indexed file store for chat attachments.

    The index lives at ``$FERAL_HOME/uploads/index.json`` and is the
    single source of truth for which uploads exist. The directory is
    safe to delete to reset the store — the index is rebuilt on next
    init.
    """

    INDEX_NAME = "index.json"

    def __init__(
        self,
        *,
        root: Optional[Path] = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        self._root = Path(root or (feral_data_home() / "uploads"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_path = self._root / self.INDEX_NAME
        self._max_file_bytes = max(1, int(max_file_bytes))
        self._max_total_bytes = max(self._max_file_bytes, int(max_total_bytes))
        self._lock = threading.Lock()
        self._index: dict[str, dict] = self._load_index()

    # ── Index plumbing ────────────────────────────────────────────

    def _load_index(self) -> dict[str, dict]:
        if not self._index_path.exists():
            return {}
        try:
            with self._index_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.warning("upload index unreadable, rebuilding: %s", exc)
        return {}

    def _persist_index(self) -> None:
        tmp = self._index_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, sort_keys=True)
        os.replace(tmp, self._index_path)

    # ── Public API ────────────────────────────────────────────────

    @property
    def root(self) -> Path:
        return self._root

    @property
    def max_file_bytes(self) -> int:
        return self._max_file_bytes

    @property
    def max_total_bytes(self) -> int:
        return self._max_total_bytes

    def total_bytes(self) -> int:
        return sum(int(r.get("size_bytes", 0)) for r in self._index.values())

    def store(
        self,
        *,
        data: bytes,
        filename: str,
        content_type: str = "",
        extra: Optional[dict] = None,
    ) -> UploadRecord:
        size = len(data)
        if size <= 0:
            raise ValueError("upload data is empty")
        if size > self._max_file_bytes:
            raise UploadQuotaExceeded(
                f"file size {size} exceeds per-upload limit {self._max_file_bytes}"
            )

        with self._lock:
            total_after = self.total_bytes() + size
            if total_after > self._max_total_bytes:
                raise UploadQuotaExceeded(
                    f"store quota exceeded: would be {total_after} > {self._max_total_bytes}"
                )

            import hashlib

            sha = hashlib.sha256(data).hexdigest()
            # Dedup: if a record with this sha already exists, return
            # it instead of writing the bytes twice. The UI's attachment
            # chip still shows the original filename.
            existing = next(
                (r for r in self._index.values() if r.get("sha256") == sha),
                None,
            )
            if existing is not None:
                return UploadRecord(**{**existing, "path": str(self._root / existing["upload_id"])})

            upload_id = uuid4().hex
            dest = self._root / upload_id
            dest.write_bytes(data)

            record = UploadRecord(
                upload_id=upload_id,
                filename=filename or "untitled",
                content_type=content_type or "application/octet-stream",
                size_bytes=size,
                sha256=sha,
                created_at=time.time(),
                path=str(dest),
                extra=dict(extra or {}),
            )
            self._index[upload_id] = {
                k: v for k, v in record.as_dict().items() if k != "path"
            }
            self._persist_index()
            return record

    def get(self, upload_id: str) -> Optional[UploadRecord]:
        with self._lock:
            row = self._index.get(upload_id)
            if row is None:
                return None
            return UploadRecord(**{**row, "path": str(self._root / upload_id)})

    def list_recent(self, limit: int = 50) -> list[UploadRecord]:
        with self._lock:
            rows = sorted(
                self._index.values(),
                key=lambda r: float(r.get("created_at", 0.0)),
                reverse=True,
            )[:limit]
        return [UploadRecord(**{**r, "path": str(self._root / r["upload_id"])}) for r in rows]

    def delete(self, upload_id: str) -> bool:
        with self._lock:
            if upload_id not in self._index:
                return False
            self._index.pop(upload_id, None)
            self._persist_index()
        try:
            (self._root / upload_id).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("upload file unlink failed: %s", exc)
        return True

    def stats(self) -> dict:
        with self._lock:
            return {
                "count": len(self._index),
                "total_bytes": self.total_bytes(),
                "max_file_bytes": self._max_file_bytes,
                "max_total_bytes": self._max_total_bytes,
                "root": str(self._root),
            }


__all__ = [
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_TOTAL_BYTES",
    "UploadQuotaExceeded",
    "UploadRecord",
    "UploadStore",
]
