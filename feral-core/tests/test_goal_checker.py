"""PR 7: deterministic done/blocked/continue verdicts.

The matrix below pins the priority order (BLOCKED outranks DONE
outranks CONTINUE) and verifies that each blocking signal surfaces
operator-actionable remediation text. The goal checker is the
runtime's safety floor between micro-steps; a regression here would
hide stalls and silently exhaust budgets, which is exactly the
'fake readiness' failure mode PR 7 exists to prevent.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.goal_checker import (  # noqa: E402
    GoalContext, GoalVerdict, check_goal,
)


def test_permission_needed_blocks_with_remediation():
    ctx = GoalContext(
        goal_text="write to Desktop",
        permission_needed=True,
        permission_target="Desktop",
        permission_setup_step="Run `feral grant Desktop ~/Desktop`",
    )
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.BLOCKED
    assert "Permission required" in decision.reason
    assert "feral grant" in decision.remediation


def test_pending_approval_blocks_before_done_evaluates():
    """Approval BLOCKED must outrank DONE — a side-step awaiting
    confirmation must not be hidden under a 'main objective satisfied'
    verdict."""
    ctx = GoalContext(
        pending_approval=True,
        pending_approval_tool="computer_use__bash",
        pending_approval_reason="dangerous command",
        success_criteria=[("always true", lambda _c: True)],
    )
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.BLOCKED
    assert "Awaiting approval" in decision.reason


def test_too_many_consecutive_failures_blocks():
    ctx = GoalContext(
        consecutive_failures=3,
        max_consecutive_failures=3,
        last_error="ENOENT: missing manifest",
    )
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.BLOCKED
    assert "consecutive failures" in decision.reason


def test_iteration_budget_blocks():
    ctx = GoalContext(iteration=50, max_iterations=50)
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.BLOCKED
    assert "Iteration budget" in decision.reason


def test_wall_clock_blocks_when_exceeded():
    ctx = GoalContext(elapsed_seconds=70.0, max_seconds=60.0)
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.BLOCKED
    assert "Wall-clock" in decision.reason


def test_stalled_blocks_when_no_progress_for_threshold_iterations():
    ctx = GoalContext(
        iterations_since_progress=5,
        stall_threshold=5,
        progress_delta=0,
    )
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.BLOCKED
    assert "Stalled" in decision.reason


def test_progress_resets_stall_signal():
    """A positive progress_delta means the loop is moving; even at the
    stall threshold the checker must NOT block."""
    ctx = GoalContext(
        iterations_since_progress=5,
        stall_threshold=5,
        progress_delta=0.5,
    )
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.CONTINUE


def test_all_criteria_satisfied_returns_done():
    ctx = GoalContext(
        success_criteria=[
            ("file exists", lambda _c: True),
            ("test passes", lambda _c: True),
        ],
    )
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.DONE
    assert "satisfied" in decision.reason.lower()


def test_partial_criteria_returns_continue():
    ctx = GoalContext(
        success_criteria=[
            ("file exists", lambda _c: True),
            ("test passes", lambda _c: False),
        ],
    )
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.CONTINUE


def test_no_criteria_returns_continue():
    """A loop without explicit success criteria can only stop on a
    blocking signal — it must NOT prematurely DONE itself."""
    decision = check_goal(GoalContext())
    assert decision.verdict == GoalVerdict.CONTINUE


def test_criterion_raising_does_not_satisfy_done():
    """A predicate that raises is treated as failed (defensive)."""
    def _boom(_c):
        raise RuntimeError("predicate error")
    ctx = GoalContext(success_criteria=[("boom", _boom)])
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.CONTINUE


def test_blocked_outranks_done_when_both_signals_present():
    """Belt-and-braces: a permission BLOCK must beat a satisfied DONE
    in the priority order."""
    ctx = GoalContext(
        permission_needed=True,
        permission_target="Camera",
        success_criteria=[("done", lambda _c: True)],
    )
    decision = check_goal(ctx)
    assert decision.verdict == GoalVerdict.BLOCKED
