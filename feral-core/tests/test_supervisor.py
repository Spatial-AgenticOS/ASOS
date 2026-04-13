"""Tests for the Supervisor-Aware Process Management module."""

import os
import signal
import pytest

from infra.supervisor import (
    SupervisorKind,
    SupervisorInfo,
    acquire_pid_file,
    detect_supervisor,
    install_signal_handlers,
    register_shutdown_hook,
    request_restart,
    _pid_is_alive,
    _release_pid_file,
    _shutdown_hooks,
)


class TestDetectSupervisor:
    def test_returns_supervisor_info(self):
        info = detect_supervisor()
        assert isinstance(info, SupervisorInfo)
        assert isinstance(info.kind, SupervisorKind)

    def test_bare_metal_not_managed(self, monkeypatch, tmp_path):
        monkeypatch.delenv("INVOCATION_ID", raising=False)
        monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
        monkeypatch.delenv("container", raising=False)
        info = detect_supervisor()
        if info.kind is SupervisorKind.NONE:
            assert info.managed_restart is False


class TestPidFile:
    def test_acquire_creates_file(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        result = acquire_pid_file(pid_path)
        assert result == pid_path
        assert pid_path.exists()
        assert int(pid_path.read_text().strip()) == os.getpid()

    def test_acquire_cleans_stale(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        pid_path.write_text("99999999")
        result = acquire_pid_file(pid_path)
        assert result == pid_path
        assert int(pid_path.read_text().strip()) == os.getpid()

    def test_acquire_raises_if_live(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        # PID 1 (init/launchd) is always alive and is never our own PID
        pid_path.write_text("1")
        with pytest.raises(RuntimeError, match="Another FERAL process"):
            acquire_pid_file(pid_path)

    def test_release_removes_own_pid(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        pid_path.write_text(str(os.getpid()))
        _release_pid_file(pid_path)
        assert not pid_path.exists()

    def test_release_ignores_other_pid(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        pid_path.write_text("99999999")
        _release_pid_file(pid_path)
        assert pid_path.exists()


class TestPidIsAlive:
    def test_current_process(self):
        assert _pid_is_alive(os.getpid()) is True

    def test_invalid_pid(self):
        assert _pid_is_alive(0) is False
        assert _pid_is_alive(-1) is False

    def test_nonexistent_pid(self):
        assert _pid_is_alive(4_000_000) is False


class TestShutdownHooks:
    def test_register_hook(self):
        original_len = len(_shutdown_hooks)
        register_shutdown_hook(lambda: None)
        assert len(_shutdown_hooks) == original_len + 1
        _shutdown_hooks.pop()

    def test_install_signal_handlers(self):
        install_signal_handlers()
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not None
        assert callable(handler)


class TestRequestRestart:
    def test_managed_exits(self):
        info = SupervisorInfo(kind=SupervisorKind.DOCKER, managed_restart=True)
        with pytest.raises(SystemExit) as exc_info:
            request_restart(info)
        assert exc_info.value.code == 0
