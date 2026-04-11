"""
FERAL Memory Ingest Pipeline
=============================
Utilities for bulk ingestion into notes + wiki compile.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from memory.embeddings import chunk_text

DEFAULT_REPO_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml", ".md", ".txt",
    ".sh", ".toml", ".ini", ".cfg", ".sql", ".go", ".rs", ".java", ".swift", ".kt",
    ".html", ".css",
}

DEFAULT_IGNORED_DIRS = {
    ".git", ".idea", ".vscode", "__pycache__", "node_modules", "dist", "build", ".next",
    ".venv", "venv", ".mypy_cache", ".pytest_cache", ".cursor",
}


def _is_text_bytes(raw: bytes) -> bool:
    if b"\x00" in raw:
        return False
    return True


def _read_text(path: Path, max_chars: int = 60_000) -> str:
    raw = path.read_bytes()
    if not _is_text_bytes(raw):
        return ""
    text = raw.decode("utf-8", errors="ignore").strip()
    if not text:
        return ""
    return text[:max_chars]


class MemoryIngestor:
    def __init__(self, memory_store):
        self.memory = memory_store

    def _save_chunks(self, text: str, *, source: str, tags: Iterable[str]) -> int:
        chunks = chunk_text(text, max_tokens=350, overlap=70)
        count = 0
        for i, chunk in enumerate(chunks):
            payload = chunk.strip()
            if not payload:
                continue
            self.memory.save(
                content=payload,
                tags=list(tags),
                importance="normal",
                source=f"{source}:chunk_{i + 1}",
            )
            count += 1
        return count

    def ingest_text(self, *, content: str, source_label: str = "manual", compile_after: bool = True) -> dict:
        payload = (content or "").strip()
        if not payload:
            raise ValueError("content is required")

        notes_saved = self._save_chunks(
            payload,
            source=f"ingest:text:{source_label}",
            tags=["ingest", "text"],
        )
        compile_result = self.memory.wiki_compile() if compile_after else {"compiled": False}
        return {
            "ok": True,
            "source": "text",
            "source_label": source_label,
            "notes_saved": notes_saved,
            "compile": compile_result,
        }

    def ingest_pdf(self, *, path: str, compile_after: bool = True) -> dict:
        pdf_path = Path(path).expanduser()
        if not pdf_path.exists():
            raise ValueError(f"File not found: {pdf_path}")
        if not pdf_path.is_file():
            raise ValueError(f"Not a file: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise ValueError("path must point to a .pdf file")

        try:
            import fitz  # PyMuPDF
        except ImportError as e:
            raise ValueError("PyMuPDF is required for PDF ingest (`pip install pymupdf`)") from e

        pages: list[str] = []
        doc = fitz.open(str(pdf_path))
        try:
            for i in range(doc.page_count):
                page = doc.load_page(i)
                page_text = (page.get_text("text") or "").strip()
                if page_text:
                    pages.append(f"--- Page {i + 1} ---\n{page_text}")
        finally:
            doc.close()

        merged = "\n\n".join(pages).strip()
        if not merged:
            raise ValueError("PDF has no extractable text")

        notes_saved = self._save_chunks(
            merged,
            source=f"ingest:pdf:{pdf_path.name}",
            tags=["ingest", "pdf"],
        )
        compile_result = self.memory.wiki_compile() if compile_after else {"compiled": False}
        return {
            "ok": True,
            "source": "pdf",
            "path": str(pdf_path),
            "pages_read": len(pages),
            "notes_saved": notes_saved,
            "compile": compile_result,
        }

    def ingest_repo(
        self,
        *,
        path: str,
        extensions_filter: list[str] | None = None,
        compile_after: bool = True,
        max_files: int = 300,
    ) -> dict:
        root = Path(path).expanduser()
        if not root.exists():
            raise ValueError(f"Path not found: {root}")
        if not root.is_dir():
            raise ValueError(f"Path is not a directory: {root}")

        allowed = {ext if ext.startswith(".") else f".{ext}" for ext in (extensions_filter or DEFAULT_REPO_EXTENSIONS)}
        files_processed = 0
        files_skipped = 0
        notes_saved = 0

        for file_path in root.rglob("*"):
            if files_processed >= max_files:
                break
            if not file_path.is_file():
                continue
            if any(part in DEFAULT_IGNORED_DIRS for part in file_path.parts):
                continue
            if allowed and file_path.suffix.lower() not in allowed:
                files_skipped += 1
                continue

            try:
                text = _read_text(file_path, max_chars=80_000)
            except Exception:
                files_skipped += 1
                continue
            if not text:
                files_skipped += 1
                continue

            rel = str(file_path.relative_to(root))
            file_blob = f"# File: {rel}\n\n{text}"
            notes_saved += self._save_chunks(
                file_blob,
                source=f"ingest:repo:{rel}",
                tags=["ingest", "repo"],
            )
            files_processed += 1

        compile_result = self.memory.wiki_compile() if compile_after else {"compiled": False}
        return {
            "ok": True,
            "source": "repo",
            "path": str(root),
            "files_processed": files_processed,
            "files_skipped": files_skipped,
            "notes_saved": notes_saved,
            "compile": compile_result,
        }
