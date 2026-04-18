from __future__ import annotations

import pytest

from skills.impl import get_implementation
from skills.impl.code_interpreter import CodeInterpreterSkill


def test_code_interpreter_registered() -> None:
    impl = get_implementation("code_interpreter")
    assert impl is not None


@pytest.mark.asyncio
async def test_code_interpreter_unknown_endpoint() -> None:
    impl = get_implementation("code_interpreter")
    assert impl is not None
    out = await impl.execute("unknown", {}, {})
    assert out["success"] is False
    assert out["status_code"] == 404


@pytest.mark.asyncio
async def test_code_interpreter_captures_csv_artifact(tmp_path, monkeypatch) -> None:
    # Force the host-subprocess path. On CI the Docker binary is on PATH but
    # running `--user nobody` against the tmp mount fails with a permission
    # error that has nothing to do with the skill's artifact-capture logic.
    monkeypatch.setattr(
        "skills.impl.code_interpreter.DOCKER_AVAILABLE", False, raising=False
    )
    monkeypatch.setenv("FERAL_ARTIFACTS_DIR", str(tmp_path))
    skill = CodeInterpreterSkill()
    code = (
        "from pathlib import Path\n"
        "Path('out.csv').write_text('col1,col2\\n1,2\\n')\n"
        "print('done')\n"
    )
    out = await skill.execute("run_python", {"code": code, "timeout": 20}, {})
    assert out["status_code"] == 200
    assert out["success"] is True
    artifacts = out["data"]["artifacts"]
    assert any(a["name"] == "out.csv" for a in artifacts)
