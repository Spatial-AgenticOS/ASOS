"""Tiny state machine that drives the linear wizard flow with back/quit."""

from __future__ import annotations

import inspect
import logging
from typing import Awaitable, Callable, Sequence

from .helpers import BackNavigation, QuitNavigation, SkipStep, get_console
from .state import WizardState

logger = logging.getLogger("feral.cli.setup.state_machine")


StepFn = Callable[[WizardState], "Awaitable[None] | None"]


class StateMachine:
    """Run steps in order, supporting ``back`` and ``quit`` navigation."""

    def __init__(self, *, state: WizardState, steps: Sequence[tuple[str, StepFn]]):
        self.state = state
        self.steps = list(steps)
        self.console = get_console()

    async def run(self) -> None:
        idx = 0
        while idx < len(self.steps):
            name, fn = self.steps[idx]
            try:
                result = fn(self.state)
                if inspect.isawaitable(result):
                    await result
                self.state.completed_steps.add(name)
                idx += 1
            except BackNavigation:
                if idx == 0:
                    self.console.print("(can't go back from the first step)")
                    continue
                idx -= 1
            except SkipStep:
                idx += 1
            except QuitNavigation:
                self.console.print("Setup paused — run `feral setup` again when you're ready.")
                return
            except Exception as exc:
                # Unexpected error in a step: log + continue so the user
                # can still finish the wizard instead of the whole thing
                # exploding. The step's own error handling should catch
                # recoverable issues before this.
                logger.exception("step %s raised", name)
                self.console.print(f"[red]Step {name!r} failed: {exc}.[/] Continuing.")
                idx += 1
