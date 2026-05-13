"""PR2: ``computer_use__bash`` must refuse host fallback when the
manifest declares ``requires_sandbox: true``.

The previous behaviour silently fell back to ``asyncio.create_subprocess_shell``
on the host with ``sandbox=host`` whenever Docker was missing, which
contradicts the canonical-execution promise. The executor now
injects ``_feral_require_sandbox=True`` into args when the endpoint
requires sandbox; the impl must honour it by returning a 503 error
that names the missing setup step instead of running on the host.
"""

from __future__ import annotations

import pytest

from skills.impl.computer_use import ComputerUseSkill


@pytest.mark.asyncio
async def test_bash_refuses_host_when_sandbox_required_and_docker_missing(monkeypatch) -> None:
    skill = ComputerUseSkill()

    # Force the docker probe to report nothing healthy — same situation
    # as a laptop without Docker Desktop running.
    monkeypatch.setattr(skill, "_resolve_docker_sandbox", lambda: None)

    result = await skill.execute(
        "bash",
        {"command": "echo hi", "_feral_require_sandbox": True},
        vault={},
    )

    assert result["success"] is False
    assert result["status_code"] == 503
    err = result.get("error", "") or ""
    assert "Docker sandbox" in err
    data = result.get("data") or {}
    assert data.get("sandbox") == "unavailable"
    setup = data.get("setup_step") or ""
    assert "Docker" in setup
    # Crucially: must NOT have executed on host. We assert this by the
    # absence of stdout/exit_code keys.
    assert "stdout" not in data
    assert "exit_code" not in data


@pytest.mark.asyncio
async def test_bash_runs_on_host_when_sandbox_not_required(monkeypatch) -> None:
    """Without ``requires_sandbox``, the host path is still allowed
    (matches the historical ``computer_use`` UX). Docker doesn't need
    to be present."""
    skill = ComputerUseSkill()

    monkeypatch.setattr(skill, "_resolve_docker_sandbox", lambda: None)
    monkeypatch.setenv("FERAL_SANDBOX_BASH", "false")

    result = await skill.execute("bash", {"command": "echo canonical-test"}, vault={})
    assert result["success"] is True
    data = result.get("data") or {}
    assert data.get("sandbox") == "host"
    assert "canonical-test" in (data.get("stdout") or "")
