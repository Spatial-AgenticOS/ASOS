"""
End-to-end test of the CodingRun loop on a tiny fixture repo.

The fixture is a self-contained one-file pytest project under a tmp
dir. It starts with a deliberate bug — ``add(x, y) = x - y`` — so
the test_command (`python -m pytest -q test_math.py`) initially
fails. A deterministic planner is wired in to swap ``-`` for ``+``;
the runner should:

1. Run the test command, observe exit != 0.
2. Ask the planner for an edit, parse the failure hint.
3. Apply the edit through the workspace path.
4. Rerun the test command, observe exit == 0, mark COMPLETED.

Why deterministic planner?  The CodingRunner contract takes a
pluggable planner so production wires the LLM and tests stay
reproducible. This test pins the *loop semantics* and the persisted
state shape, not the LLM's planning quality.

Side checks:
* The runner refuses to write outside the run's workspace_root.
* Forbidden test commands (`git`, `rm`, `sudo`) are rejected before
  any subprocess starts.
* The persisted steps record the actual pytest exit code and a
  stdout tail; we don't silently overwrite with "ok".
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from agents.coding_run import (  # noqa: E402
    CodingRunStatus,
    CodingRunStore,
    CodingRunner,
    EditProposal,
    PlanResult,
    _parse_failing_test_hint,
    new_run,
)


def _write(p: Path, contents: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(contents).lstrip("\n"))


def _build_failing_repo(repo: Path) -> None:
    """A pytest project where `add(2, 3)` returns -1 instead of 5."""
    _write(repo / "math_utils.py", """
        def add(x, y):
            return x - y
    """)
    _write(repo / "test_math.py", """
        from math_utils import add

        def test_addition_basic():
            assert add(2, 3) == 5

        def test_addition_zero():
            assert add(0, 0) == 0
    """)


@pytest.mark.asyncio
async def test_failing_repo_repaired_to_passing(tmp_path):
    repo = tmp_path / "repo"
    _build_failing_repo(repo)

    store = CodingRunStore(tmp_path / "coding_runs.db")
    run = new_run(
        workspace_root=str(repo),
        goal="repair add() so test_addition_basic passes",
        test_command=f"{sys.executable} -m pytest -q test_math.py",
        max_iterations=3,
    )
    store.insert(run)

    plan_calls = []

    async def deterministic_planner(_run, stdout_tail, stderr_tail, hint):
        plan_calls.append({"hint": hint, "stdout": stdout_tail, "stderr": stderr_tail})
        return PlanResult(
            edits=[
                EditProposal(
                    path="math_utils.py",
                    find="return x - y",
                    replace="return x + y",
                    rationale="swap subtraction for addition",
                ),
            ],
            summary="swap operator",
        )

    runner = CodingRunner(store)
    result = await runner.execute(run=run, planner=deterministic_planner)

    assert result.status == CodingRunStatus.COMPLETED.value, (
        f"run should complete after repair; got {result.status} (error={result.error!r}); "
        f"stdout tail:\n{result.last_stdout_tail}\nstderr tail:\n{result.last_stderr_tail}"
    )
    assert result.last_exit_code == 0
    assert result.iterations_used >= 2  # one to observe failure, one to confirm green
    assert (repo / "math_utils.py").read_text().strip() == "def add(x, y):\n    return x + y"
    # We asked once with a failing hint, never spun in a loop.
    assert len(plan_calls) == 1
    assert plan_calls[0]["hint"]  # pytest produced a FAILED line we parsed


@pytest.mark.asyncio
async def test_planner_give_up_marks_failed(tmp_path):
    repo = tmp_path / "repo"
    _build_failing_repo(repo)
    store = CodingRunStore(tmp_path / "coding_runs.db")
    run = new_run(
        workspace_root=str(repo),
        goal="impossible",
        test_command=f"{sys.executable} -m pytest -q test_math.py",
        max_iterations=2,
    )
    store.insert(run)

    async def quitter(_run, _o, _e, _h):
        return PlanResult(give_up=True, give_up_reason="cannot solve")

    runner = CodingRunner(store)
    result = await runner.execute(run=run, planner=quitter)
    assert result.status == CodingRunStatus.FAILED.value
    assert "cannot solve" in result.error


@pytest.mark.asyncio
async def test_max_iterations_exhausted_marks_failed(tmp_path):
    repo = tmp_path / "repo"
    _build_failing_repo(repo)
    store = CodingRunStore(tmp_path / "coding_runs.db")
    run = new_run(
        workspace_root=str(repo),
        goal="loop forever",
        test_command=f"{sys.executable} -m pytest -q test_math.py",
        max_iterations=2,
    )
    store.insert(run)

    async def noop_edit(_run, _o, _e, _h):
        # Apply a non-fix that keeps the test failing every iteration.
        return PlanResult(
            edits=[
                EditProposal(
                    path="math_utils.py",
                    find="def add",
                    replace="def add",  # idempotent
                    rationale="no real fix",
                ),
            ]
        )

    runner = CodingRunner(store)
    result = await runner.execute(run=run, planner=noop_edit)
    assert result.status == CodingRunStatus.FAILED.value
    assert "max_iterations" in result.error
    assert result.iterations_used == run.max_iterations


@pytest.mark.asyncio
async def test_refuses_write_outside_workspace(tmp_path):
    repo = tmp_path / "repo"
    _build_failing_repo(repo)
    outside = tmp_path / "outside.txt"
    outside.write_text("def add(x, y): return x - y\n")

    store = CodingRunStore(tmp_path / "coding_runs.db")
    run = new_run(
        workspace_root=str(repo),
        goal="evil",
        test_command=f"{sys.executable} -m pytest -q test_math.py",
        max_iterations=2,
    )
    store.insert(run)

    async def escaping(_run, _o, _e, _h):
        return PlanResult(
            edits=[
                EditProposal(
                    path=str(outside),  # absolute path outside workspace
                    find="def add",
                    replace="def add",
                ),
            ],
        )

    runner = CodingRunner(store)
    result = await runner.execute(run=run, planner=escaping)
    assert result.status == CodingRunStatus.FAILED.value
    assert "outside" in (result.error or "")


@pytest.mark.asyncio
async def test_refuses_git_test_command(tmp_path):
    repo = tmp_path / "repo"
    _build_failing_repo(repo)
    store = CodingRunStore(tmp_path / "coding_runs.db")
    run = new_run(
        workspace_root=str(repo),
        goal="should refuse",
        test_command="git status",
    )
    store.insert(run)

    async def never_called(*_args, **_kwargs):
        raise AssertionError("planner should not be called when test_command is forbidden")

    runner = CodingRunner(store)
    result = await runner.execute(run=run, planner=never_called)
    assert result.status == CodingRunStatus.FAILED.value
    assert "git" in (result.error or "")


@pytest.mark.asyncio
async def test_missing_workspace_marks_failed(tmp_path):
    store = CodingRunStore(tmp_path / "coding_runs.db")
    run = new_run(
        workspace_root=str(tmp_path / "does_not_exist"),
        goal="no repo",
        test_command="echo hi",
    )
    store.insert(run)

    async def never(_r, _o, _e, _h):
        raise AssertionError("should short-circuit before planning")

    runner = CodingRunner(store)
    result = await runner.execute(run=run, planner=never)
    assert result.status == CodingRunStatus.FAILED.value
    assert "not a directory" in (result.error or "")


# ── Parser ────────────────────────────────────────────────────────────


def test_parse_failing_test_hint_pytest_summary_line():
    out = "============= FAILED test_math.py::test_addition_basic - assert -1 == 5"
    assert _parse_failing_test_hint(out, "") == "test_math.py::test_addition_basic"


def test_parse_failing_test_hint_traceback_file_header():
    err = "math_utils.py:2: AssertionError\n"
    assert _parse_failing_test_hint("", err) == "math_utils.py"


def test_parse_failing_test_hint_empty_returns_empty():
    assert _parse_failing_test_hint("", "") == ""


# ── Store round-trip ──────────────────────────────────────────────────


def test_store_round_trips_run_and_steps(tmp_path):
    store = CodingRunStore(tmp_path / "coding_runs.db")
    run = new_run(workspace_root=str(tmp_path), goal="t", test_command="echo ok")
    store.insert(run)
    fetched = store.get(run.id)
    assert fetched is not None
    assert fetched.id == run.id
    assert fetched.workspace_root == str(tmp_path)

    from agents.coding_run import CodingRunStep
    store.append_step(run.id, CodingRunStep(
        index=1, phase="run_tests", status="ok",
        summary="echo ok", command="echo ok", exit_code=0,
        stdout_tail="ok\n", stderr_tail="",
    ))
    steps = store.list_steps(run.id)
    assert len(steps) == 1
    assert steps[0].command == "echo ok"
    assert steps[0].exit_code == 0


def test_list_recent_returns_runs_newest_first(tmp_path):
    store = CodingRunStore(tmp_path / "coding_runs.db")
    a = new_run(workspace_root=str(tmp_path), goal="a", test_command="echo a")
    store.insert(a)
    # Force the second run's updated_at to be strictly later — sqlite WAL
    # journal otherwise returns identical floats on fast hardware.
    import time as _t
    _t.sleep(0.01)
    b = new_run(workspace_root=str(tmp_path), goal="b", test_command="echo b")
    store.insert(b)
    listing = store.list_recent()
    assert listing[0].id == b.id
    assert listing[1].id == a.id


_ = asyncio  # keep imports quiet — asyncio is used by pytest-asyncio under the hood
