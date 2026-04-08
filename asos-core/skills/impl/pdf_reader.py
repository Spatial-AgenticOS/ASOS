"""
THEORA PDF Reader Skill
=======================
Extract text from local PDF files using PyMuPDF.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

from skills.base import BaseSkill
from skills.impl import register_skill

MAX_CHARS = 200_000


@register_skill
class PDFReaderSkill(BaseSkill):
    def __init__(self):
        super().__init__(skill_id="pdf_reader")

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        _ = vault
        if endpoint_id not in ("extract_text", "extract"):
            return {
                "success": False,
                "status_code": 404,
                "data": None,
                "error": f"Unknown endpoint: {endpoint_id}",
            }

        raw_path = str(args.get("path", "")).strip()
        if not raw_path:
            return {"success": False, "status_code": 400, "data": None, "error": "path is required"}

        path = Path(raw_path).expanduser()
        if not path.exists():
            return {"success": False, "status_code": 404, "data": None, "error": f"File not found: {path}"}
        if not path.is_file():
            return {"success": False, "status_code": 400, "data": None, "error": f"Not a file: {path}"}

        page_start = max(1, int(args.get("page_start", 1) or 1))
        page_end = int(args.get("page_end", 0) or 0)
        max_chars = max(1_000, min(int(args.get("max_chars", 60_000) or 60_000), MAX_CHARS))

        try:
            data = await asyncio.to_thread(
                self._extract_text,
                path=path,
                page_start=page_start,
                page_end=page_end,
                max_chars=max_chars,
            )
            return {"success": True, "status_code": 200, "data": data, "error": None}
        except Exception as e:
            return {"success": False, "status_code": 500, "data": None, "error": str(e)}

    @staticmethod
    def _extract_text(path: Path, page_start: int, page_end: int, max_chars: int) -> dict:
        try:
            import fitz  # PyMuPDF
        except ImportError as e:
            raise RuntimeError("PyMuPDF is required for pdf_reader. Install it with: pip install pymupdf") from e

        doc = fitz.open(str(path))
        try:
            total_pages = int(doc.page_count)
            if total_pages == 0:
                return {
                    "path": str(path),
                    "total_pages": 0,
                    "pages_read": 0,
                    "start_page": 0,
                    "end_page": 0,
                    "truncated": False,
                    "text": "",
                }

            start_idx = min(max(page_start - 1, 0), total_pages - 1)
            if page_end <= 0:
                end_idx = total_pages - 1
            else:
                end_idx = min(max(page_end - 1, start_idx), total_pages - 1)

            text_parts: list[str] = []
            char_count = 0
            truncated = False
            pages_read = 0

            for i in range(start_idx, end_idx + 1):
                page = doc.load_page(i)
                page_text = page.get_text("text") or ""
                block = f"\n\n--- Page {i + 1} ---\n{page_text}".strip()
                remaining = max_chars - char_count
                if remaining <= 0:
                    truncated = True
                    break
                if len(block) > remaining:
                    text_parts.append(block[:remaining])
                    char_count += remaining
                    pages_read += 1
                    truncated = True
                    break
                text_parts.append(block)
                char_count += len(block)
                pages_read += 1

            return {
                "path": str(path),
                "total_pages": total_pages,
                "pages_read": pages_read,
                "start_page": start_idx + 1,
                "end_page": end_idx + 1,
                "truncated": truncated,
                "text": "".join(text_parts).strip(),
            }
        finally:
            doc.close()
