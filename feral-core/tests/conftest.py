import pytest
import os


# Raise the rate-limit ceiling well before the server module imports so
# CI test runs (120 req/min default is too low once we have 200+ route
# tests) don't hit 429s on one of the Hardware / config tests. Keep the
# legacy 120 in production by setting this only when FERAL_RATE_LIMIT_RPM
# is unset.
os.environ.setdefault("FERAL_RATE_LIMIT_RPM", "10000")


# W12 (FEATURE_STABILITY_ROADMAP §3.4 #3-4): soak tests are gated behind
# `--runsoak`. Without the flag every test marked `@pytest.mark.soak` is
# skipped so the regular CI run stays fast and deterministic.
def pytest_addoption(parser):
    parser.addoption(
        "--runsoak",
        action="store_true",
        default=False,
        help="run @pytest.mark.soak tests (long-duration voice/channel soak)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runsoak"):
        return
    skip_soak = pytest.mark.skip(reason="needs --runsoak option to run")
    for item in items:
        if "soak" in item.keywords:
            item.add_marker(skip_soak)


@pytest.fixture(autouse=True)
def _disable_api_key_middleware_for_tests(monkeypatch):
    """Starlette TestClient reports client host as 'testclient'; accept that as localhost
    for tests so the auth middleware bypasses without every test needing to send a header.
    Real production hosts never report 'testclient'.
    """
    from security import session_auth as _sa
    orig_is_localhost = _sa.is_localhost

    def _is_localhost_test(host):
        if host == "testclient":
            return True
        return orig_is_localhost(host)

    monkeypatch.setattr(_sa, "is_localhost", _is_localhost_test)
    try:
        import api.server as _server
        monkeypatch.setattr(_server, "is_localhost", _is_localhost_test, raising=False)
    except Exception:
        pass


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
