"""Tiny state machine that drives the linear wizard flow with back/quit."""

from __future__ import annotations

import inspect
import logging
from typing import Awaitable, Callable, Sequence

from cli import ui_kit

from .helpers import BackNavigation, QuitNavigation, SkipStep, _RICH_AVAILABLE, get_console
from .state import WizardState

logger = logging.getLogger("feral.cli.setup.state_machine")


StepFn = Callable[[WizardState], "Awaitable[None] | None"]


# Steps that handle their own framing (welcome panel, finish summary)
# get no auto step header — the indicator would only add noise.
_NO_INDICATOR_STEPS = frozenset({"welcome", "finish"})


_STEP_TITLES = {
    "llm_provider": "LLM Provider",
    "llm_model": "Model",
    "audio": "Speech in / out",
    "identity": "Identity",
    "network": "Network access",
    "home_assistant": "Home Assistant",
    "channels": "Messaging channels",
}


class StateMachine:
    """Run steps in order, supporting ``back`` and ``quit`` navigation."""

    def __init__(self, *, state: WizardState, steps: Sequence[tuple[str, StepFn]]):
        self.state = state
        self.steps = list(steps)
        self.console = get_console()

    async def run(self) -> None:
        # Total visible steps for the "Step N of M" indicator excludes
        # the framing-only welcome/finish so the operator sees the
        # familiar 1..N progress count and not a meaningless 0..N+1.
        visible_steps = [s for s, _ in self.steps if s not in _NO_INDICATOR_STEPS]
        total_visible = len(visible_steps)
        visible_idx = 0

        idx = 0
        while idx < len(self.steps):
            name, fn = self.steps[idx]
            if name not in _NO_INDICATOR_STEPS:
                visible_idx = visible_steps.index(name) + 1
                self._announce_step(name, visible_idx, total_visible)
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

    def _announce_step(self, name: str, idx: int, total: int) -> None:
        title = _STEP_TITLES.get(name, name.replace("_", " ").title())
        if _RICH_AVAILABLE:
            self.console.print()
            self.console.print(
                f"[{ui_kit.BRAND_COLOR}]──[/] [bold]Step {idx} of {total}[/] "
                f"[dim]·[/] [bold]{title}[/] "
                f"[{ui_kit.BRAND_COLOR}]" + "─" * 4 + "[/]"
            )
        else:
            self.console.print()
            self.console.print(f"── Step {idx} of {total} · {title} ────")
