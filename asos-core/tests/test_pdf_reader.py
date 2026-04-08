from __future__ import annotations

import pytest

from skills.impl import get_implementation


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
