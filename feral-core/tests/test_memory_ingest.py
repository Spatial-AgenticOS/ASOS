import os
import tempfile

import pytest

from memory.ingest import MemoryIngestor
from memory.store import MemoryStore


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = MemoryStore(db_path=path)
    yield s
    os.unlink(path)


class TestMemoryIngestor:
    async def test_ingest_text_saves_chunks(self, store):
        ingestor = MemoryIngestor(store)
        result = await ingestor.ingest_text(
            content="hello world " * 300,
            source_label="unit_test",
            compile_after=False,
        )
        assert result["ok"] is True
        assert result["notes_saved"] >= 1
        assert result["source"] == "text"

    async def test_ingest_repo_reads_text_files(self, store, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("# Repo\nThis is a test repo.")
        (repo / "main.py").write_text("print('hello from repo ingest')")
        (repo / "binary.bin").write_bytes(b"\x00\x01\x02\x03")

        ingestor = MemoryIngestor(store)
        result = await ingestor.ingest_repo(path=str(repo), compile_after=True, max_files=20)
        assert result["ok"] is True
        assert result["source"] == "repo"
        assert result["files_processed"] >= 2
        assert result["notes_saved"] >= 2
        assert result["compile"]["compiled"] is True
