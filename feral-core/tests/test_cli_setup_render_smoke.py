"""Smoke tests for the wizard's visual chrome.

Two things this file pins down:

1. The state-machine prints a "Step N of M · <title>" indicator before
   each non-framing step (welcome / finish are framing-only and must
   stay header-less so the welcome panel is the operator's first
   impression).
2. The welcome step renders the raccoon emoji + the ASCII ``FERAL``
   logo block, even on the Rich-disabled fallback path. This is what
   makes ``feral setup`` feel like a brand-name CLI on first run
   instead of a bare argparse dump.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cli.setup.state import WizardState
from cli.setup.state_machine import StateMachine
from cli.setup.steps import welcome


@pytest.fixture()
def wizard_state(tmp_path: Path) -> WizardState:
    state = WizardState(home=tmp_path / "feral")
    state.home.mkdir(parents=True, exist_ok=True)
    return state


class TestStepIndicator:
    def test_indicator_emitted_for_every_visible_step(
        self, wizard_state, capsys
    ):
        order: list[str] = []

        def make_step(name: str):
            def _step(state: WizardState) -> None:
                order.append(name)

            return _step

        steps = [
            ("llm_provider", make_step("llm_provider")),
            ("audio", make_step("audio")),
            ("identity", make_step("identity")),
        ]
        sm = StateMachine(state=wizard_state, steps=steps)
        asyncio.run(sm.run())

        captured = capsys.readouterr().out
        assert order == ["llm_provider", "audio", "identity"]
        # Indicator format must include the visible counter and the
        # human title — operators glance at this to know how far they
        # are through the wizard.
        assert "Step 1 of 3" in captured
        assert "Step 2 of 3" in captured
        assert "Step 3 of 3" in captured
        assert "LLM Provider" in captured
        assert "Speech in / out" in captured
        assert "Identity" in captured

    def test_welcome_and_finish_get_no_indicator(self, wizard_state, capsys):
        seen: list[str] = []

        def make_step(name: str):
            def _step(state: WizardState) -> None:
                seen.append(name)

            return _step

        steps = [
            ("welcome", make_step("welcome")),
            ("llm_provider", make_step("llm_provider")),
            ("finish", make_step("finish")),
        ]
        sm = StateMachine(state=wizard_state, steps=steps)
        asyncio.run(sm.run())

        captured = capsys.readouterr().out
        # The single visible step counts as 1-of-1; framing steps stay
        # quiet so the welcome panel is the first thing the operator sees.
        assert "Step 1 of 1" in captured
        assert "Step 2 of" not in captured
        assert "Step 0 of" not in captured


class TestRaccoonLogo:
    def test_welcome_renders_raccoon_and_feral_block(self, wizard_state, capsys):
        welcome.run(wizard_state)
        captured = capsys.readouterr().out
        # Raccoon emoji is the brand mark — it must appear in the
        # welcome panel regardless of Rich availability.
        assert "🦝" in captured
        # The ASCII logo uses '█' block characters; pinning a row from
        # the block is the cheapest way to assert the logo rendered
        # without coupling to exact whitespace.
        assert "█" in captured
        # Friendly intro text + nav hint must also be there.
        assert "back" in captured.lower()
