"""Regression coverage for Docker sandbox runtime hardening flags."""

from __future__ import annotations

import pytest

import security.docker_sandbox as docker_sandbox

pytestmark = pytest.mark.no_auto_feral_home


def _security_opts(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, part in enumerate(cmd[:-1]) if part == "--security-opt"]


def test_docker_base_cmd_includes_hardening_flags_by_default():
    sandbox = docker_sandbox.DockerSandbox(image="feral-sandbox:test")
    cmd = sandbox._docker_base_cmd()  # noqa: SLF001

    assert "--cap-drop" in cmd
    assert cmd[cmd.index("--cap-drop") + 1] == "ALL"
    assert "--pids-limit" in cmd
    assert cmd[cmd.index("--pids-limit") + 1] == "128"
    assert "no-new-privileges" in _security_opts(cmd)


def test_seccomp_profile_env_is_forwarded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FERAL_SANDBOX_SECCOMP_PROFILE", "/tmp/seccomp.json")
    sandbox = docker_sandbox.DockerSandbox(image="feral-sandbox:test")
    cmd = sandbox._docker_base_cmd()  # noqa: SLF001

    assert "seccomp=/tmp/seccomp.json" in _security_opts(cmd)


def test_insecure_unconfined_seccomp_is_ignored(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FERAL_SANDBOX_SECCOMP_PROFILE", "unconfined")
    sandbox = docker_sandbox.DockerSandbox(image="feral-sandbox:test")
    cmd = sandbox._docker_base_cmd()  # noqa: SLF001

    assert all(not opt.startswith("seccomp=") for opt in _security_opts(cmd))


def test_no_new_privileges_can_be_explicitly_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FERAL_SANDBOX_NO_NEW_PRIVILEGES", "false")
    sandbox = docker_sandbox.DockerSandbox(image="feral-sandbox:test")
    cmd = sandbox._docker_base_cmd()  # noqa: SLF001

    assert "no-new-privileges" not in _security_opts(cmd)


def test_default_image_uses_versioned_resolver(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        docker_sandbox,
        "_resolve_default_image",
        lambda: "feral-sandbox:resolved",
    )
    sandbox = docker_sandbox.DockerSandbox()
    assert sandbox._image == "feral-sandbox:resolved"  # noqa: SLF001
