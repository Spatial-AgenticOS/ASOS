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
def isolate_feral_home(request, tmp_path, monkeypatch):
    """Isolate tests from real ~/.feral directory.
    Skips for tests that manage FERAL_HOME themselves.
    """
    markers = {m.name for m in request.node.iter_markers()}
    if "no_auto_feral_home" in markers:
        return
    module_markers = getattr(request.module, "pytestmark", [])
    if any(getattr(m, "name", "") == "no_auto_feral_home" for m in (module_markers if isinstance(module_markers, list) else [module_markers])):
        return
    feral_dir = tmp_path / ".feral-isolation"
    monkeypatch.setenv("FERAL_HOME", str(feral_dir))
    os.makedirs(feral_dir, exist_ok=True)
