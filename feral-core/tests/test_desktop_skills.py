"""
A2 — the ``desktop_control`` and ``desktop_automation`` manifests used to
share the same ``skill_id`` ("desktop_automation"), so whichever loaded
second silently overwrote the other — and every ``desktop_control__*`` tool
id the orchestrator / refusal_handler emitted pointed at a non-existent
skill. These tests lock in the fix: both skills register under distinct
ids AND expose the endpoints the rest of the codebase already references.
"""
from __future__ import annotations

from skills.registry import SkillRegistry


def _load_builtins() -> SkillRegistry:
    reg = SkillRegistry()
    reg.load_builtin_skills()
    return reg


def test_desktop_control_registers_under_own_id():
    reg = _load_builtins()
    assert "desktop_control" in reg.skills, (
        "desktop_control manifest must own its own skill_id — if this fails "
        "the desktop_control.json vs desktop_automation.json collision is back."
    )
    skill = reg.skills["desktop_control"]
    endpoint_ids = {ep.id for ep in skill.endpoints}
    # These are the exact endpoint ids referenced from refusal_handler +
    # identity_loader; breaking them re-introduces the "model emits
    # desktop_control__shell_command as prose" bug.
    assert {"open_app", "shell_command", "screenshot", "system_info", "set_volume"}.issubset(endpoint_ids)


def test_desktop_automation_still_registers_with_mouse_keyboard_endpoints():
    reg = _load_builtins()
    assert "desktop_automation" in reg.skills
    endpoint_ids = {ep.id for ep in reg.skills["desktop_automation"].endpoints}
    assert {"click_screen", "type_text", "key_combo", "scroll"}.issubset(endpoint_ids)


def test_both_desktop_skills_coexist():
    reg = _load_builtins()
    assert reg.skills["desktop_control"] is not reg.skills["desktop_automation"]


def test_desktop_control_tool_ids_are_llm_resolvable():
    """The LLM tool-id format is ``<skill_id>__<endpoint_id>``. The exact
    strings below appear hardcoded in ``agents/refusal_handler.py`` and
    ``agents/identity_loader.py``; this test is the canary that catches a
    manifest rename before it silently strands them."""
    reg = _load_builtins()
    tool_names = {t["function"]["name"] for t in reg.get_all_tools()}
    assert "desktop_control__open_app" in tool_names
    assert "desktop_control__shell_command" in tool_names
