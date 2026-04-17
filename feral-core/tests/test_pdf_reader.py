from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skills.impl import get_implementation
from skills.impl.pdf_reader import PDFReaderSkill, MAX_PAGES


def test_pdf_reader_registered() -> None:
    impl = get_implementation("pdf_reader")
    assert impl is not None


@pytest.mark.asyncio
async def test_pdf_reader_missing_path_returns_404() -> None:
    impl = get_implementation("pdf_reader")
    assert impl is not None
    out = await impl.execute("extract_text", {"path": "/tmp/definitely_missing_file.pdf"}, {})
    assert out["success"] is False
    assert out["status_code"] == 404


def _create_pdf(tmp_path: Path, pages: int = 1, text: str = "Hello FERAL") -> Path:
    """Create a minimal PDF using PyMuPDF."""
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{text} page {i + 1}")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.mark.asyncio
async def test_pdf_extract_text_from_real_pdf(tmp_path) -> None:
    pdf_path = _create_pdf(tmp_path, pages=2)
    impl = get_implementation("pdf_reader")
    out = await impl.execute("extract_text", {"path": str(pdf_path)}, {})
    assert out["success"] is True
    assert out["data"]["total_pages"] == 2
    assert "Hello FERAL" in out["data"]["text"]


@pytest.mark.asyncio
async def test_pdf_metadata_extraction(tmp_path) -> None:
    pdf_path = _create_pdf(tmp_path, pages=1)
    impl = get_implementation("pdf_reader")
    out = await impl.execute("metadata", {"path": str(pdf_path)}, {})
    assert out["success"] is True
    assert out["data"]["page_count"] == 1


@pytest.mark.asyncio
async def test_pdf_table_extraction(tmp_path) -> None:
    """Table-heavy PDF: verify tables list is returned (may be empty for simple PDFs)."""
    pdf_path = _create_pdf(tmp_path, pages=1, text="Col1 Col2\nA B")
    impl = get_implementation("pdf_reader")
    out = await impl.execute("extract_text", {"path": str(pdf_path)}, {})
    assert out["success"] is True
    assert isinstance(out["data"]["tables"], list)


@pytest.mark.asyncio
async def test_pdf_corrupt_returns_graceful_error(tmp_path) -> None:
    bad_path = tmp_path / "corrupt.pdf"
    bad_path.write_bytes(b"not a pdf at all")
    impl = get_implementation("pdf_reader")
    out = await impl.execute("extract_text", {"path": str(bad_path)}, {})
    assert out["success"] is False
    assert out["status_code"] == 500
    assert out["error"] is not None


@pytest.mark.asyncio
async def test_pdf_too_many_pages_rejected(tmp_path) -> None:
    """A mock PDF with page_count > MAX_PAGES is rejected cleanly."""
    fitz = pytest.importorskip("fitz")
    pdf_path = _create_pdf(tmp_path, pages=1)

    mock_doc = MagicMock()
    mock_doc.page_count = MAX_PAGES + 1
    mock_doc.close = MagicMock()

    with patch("skills.impl.pdf_reader._get_fitz") as mock_fitz:
        mock_fitz.return_value.open.return_value = mock_doc
        impl = get_implementation("pdf_reader")
        out = await impl.execute("extract_text", {"path": str(pdf_path)}, {})
        assert out["success"] is False
        assert "limit" in out["error"].lower() or str(MAX_PAGES) in out["error"]
