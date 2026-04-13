import pytest
import os


@pytest.fixture
def temp_db(tmp_path):
    """Provide a temporary SQLite database path."""
    return str(tmp_path / "test_memory.db")


@pytest.fixture
def mock_vault():
    """A mock vault that returns test keys."""
    class MockVault:
        def get(self, key, default=""):
            return f"test-{key}"
        def inject_headers(self, skill_id, headers):
            return headers
    return MockVault()


@pytest.fixture(autouse=True)
def isolate_feral_home(tmp_path, monkeypatch):
    """Isolate tests from real ~/.feral directory.
    Uses a unique subdir to avoid colliding with test-specific fixtures
    that also create tmp_path / '.feral' (e.g. test_config.py temp_dirs).
    """
    feral_dir = tmp_path / ".feral-isolation"
    monkeypatch.setenv("FERAL_HOME", str(feral_dir))
    os.makedirs(feral_dir, exist_ok=True)
