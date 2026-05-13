"""
Provider-neutral Computer Use driver
=====================================

Anthropic, OpenAI, and FERAL's own VLM loop each emit "computer use"
actions in a different shape. Without a single normalization layer,
every backend grows its own ``if vendor == ...`` ladder, coordinate
translation drifts (DPI is applied twice or not at all), and the
shell escape hatch leaks past the sandbox boundary.

This module collapses all three dialects into a single internal IR
that the rest of FERAL already understands:

    {"action": "click", "x": 100, "y": 200}
    {"action": "type",  "text": "hello"}
    {"action": "key",   "keys": "cmd+c"}
    {"action": "scroll","direction": "down", "amount": 3}
    {"action": "screenshot"}
    {"action": "wait",  "ms": 500}
    {"action": "drag",  "path": [(x1,y1),(x2,y2),...]}
    {"action": "shell", "command": "open -a 'Google Chrome'"}
    {"action": "done",  "summary": "..."}
    {"action": "failed","reason": "..."}

Schema sources:
* Anthropic Claude computer-use ``computer_20241022`` /
  ``computer_20250124``: ``{type:"left_click", coordinate:[x,y]}``,
  ``{type:"type", text}``, ``{type:"key", text:"cmd+c"}``,
  ``{type:"scroll", coordinate:[x,y], scroll_direction, scroll_amount}``,
  ``{type:"left_click_drag", start_coordinate, coordinate}``,
  ``{type:"screenshot"}``, ``{type:"wait", duration}``,
  ``{type:"hold_key", text, duration}``.
* OpenAI Responses ``computer`` tool (GA): ``click``, ``double_click``,
  ``scroll``, ``type``, ``wait``, ``keypress``, ``drag``, ``move``,
  ``screenshot`` — coordinates as ``x``/``y`` integers, drags as a
  ``path`` of points.
* FERAL VLM JSON (already shipped, see
  ``feral-core/skills/impl/agentic_computer_use.py``):
  ``{action:"click",x,y}`` / ``{action:"type", text}`` / etc.

The driver is *coordinate-space neutral*. It does **not** apply DPI
scaling itself — that responsibility belongs to whichever primitive
runs the action (today: ``GUIComputerUseSkill._scaled_xy``). Doing it
in two places would cut the click position in half on Retina displays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


CANONICAL_ACTIONS: tuple[str, ...] = (
    "click",
    "double_click",
    "right_click",
    "type",
    "key",
    "scroll",
    "move",
    "drag",
    "screenshot",
    "wait",
    "shell",
    "done",
    "failed",
)


@dataclass
class NormalizedAction:
    """The canonical IR every CU action is normalized into.

    All optional fields default to safe zero-values so consumers can
    `.get(...)` without conditional branches. The driver guarantees:

    * ``action`` is one of :data:`CANONICAL_ACTIONS` after normalization;
      anything unrecognised yields ``None`` from :func:`normalize_action`.
    * Coordinate fields (`x`, `y`) are ints in **screenshot space** —
      the same space the VLM saw. The downstream primitive (`gui_*`)
      is responsible for DPI scaling exactly once.
    * `keys` is a single string in FERAL's "+"-joined form
      (e.g. ``"cmd+shift+t"``) regardless of how the vendor encoded it.
    """

    action: str
    x: Optional[int] = None
    y: Optional[int] = None
    text: str = ""
    keys: str = ""
    direction: str = "down"
    amount: int = 3
    duration_ms: int = 0
    path: List[Tuple[int, int]] = field(default_factory=list)
    command: str = ""
    summary: str = ""
    reason: str = ""
    description: str = ""
    provider: str = "feral"

    def to_dict(self) -> Dict[str, Any]:
        """Render the IR back as a plain dict the legacy `_execute_action`
        ladder accepts. Only fields relevant to the action are included so
        downstream type-checks don't trip on unrelated zero values."""
        out: Dict[str, Any] = {"action": self.action}
        if self.action in ("click", "double_click", "right_click", "move"):
            out["x"] = int(self.x or 0)
            out["y"] = int(self.y or 0)
        elif self.action == "type":
            out["text"] = self.text
        elif self.action == "key":
            out["keys"] = self.keys
        elif self.action == "scroll":
            out["direction"] = self.direction
            out["amount"] = int(self.amount)
            if self.x is not None and self.y is not None:
                out["x"] = int(self.x)
                out["y"] = int(self.y)
        elif self.action == "drag":
            out["path"] = [(int(px), int(py)) for px, py in self.path]
        elif self.action == "wait":
            out["ms"] = int(self.duration_ms)
        elif self.action == "shell":
            out["command"] = self.command
        elif self.action == "done":
            out["summary"] = self.summary
        elif self.action == "failed":
            out["reason"] = self.reason
        if self.description:
            out["description"] = self.description
        out["provider"] = self.provider
        return out


# ── Vendor-specific aliases ────────────────────────────────────────────
#
# Anthropic and OpenAI both speak "left_click" / "right_click" /
# "middle_click", "left_mouse_down" / "left_mouse_up", etc. The mapping
# below is conservative: anything we cannot represent losslessly stays
# in the IR but routes to the closest equivalent. Specifically:
# * `move` is preserved (gui_computer_use has `mouse_move`).
# * `keypress` collapses to `key` because FERAL's primitive accepts the
#   "+"-joined form; multiple key presses become a single combo.
# * Anthropic's `left_click_drag` and OpenAI's `drag(path)` both become
#   `drag` with a `path`.

_ANTHROPIC_TYPE_TO_FERAL: Dict[str, str] = {
    "left_click": "click",
    "left_mouse_down": "click",  # rarely emitted standalone; safest mapping
    "left_mouse_up": "click",
    "right_click": "right_click",
    "middle_click": "click",
    "double_click": "double_click",
    "triple_click": "double_click",  # FERAL has no triple_click primitive
    "type": "type",
    "key": "key",
    "hold_key": "key",
    "scroll": "scroll",
    "left_click_drag": "drag",
    "mouse_move": "move",
    "screenshot": "screenshot",
    "wait": "wait",
    "cursor_position": "screenshot",  # treat as a state-fetch; map to screenshot
}


_OPENAI_TYPE_TO_FERAL: Dict[str, str] = {
    "click": "click",
    "double_click": "double_click",
    "scroll": "scroll",
    "type": "type",
    "wait": "wait",
    "keypress": "key",
    "drag": "drag",
    "move": "move",
    "screenshot": "screenshot",
}


def _coerce_coord_pair(value: Any) -> Optional[Tuple[int, int]]:
    """Anthropic emits ``coordinate: [x, y]``. OpenAI sometimes nests as
    ``{x, y}``. This helper accepts either."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        x = value.get("x")
        y = value.get("y")
        if x is None or y is None:
            return None
        try:
            return int(x), int(y)
        except (TypeError, ValueError):
            return None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        seq = list(value)
        if len(seq) >= 2:
            try:
                return int(seq[0]), int(seq[1])
            except (TypeError, ValueError):
                return None
    return None


def _coerce_path(value: Any) -> List[Tuple[int, int]]:
    """Drag paths come in three shapes:
    * Anthropic: ``start_coordinate: [x,y], coordinate: [x,y]`` (two-point)
    * OpenAI:    ``path: [{x, y}, {x, y}, ...]``
    * FERAL VLM: ``path: [[x,y], [x,y], ...]``
    """
    if value is None:
        return []
    out: List[Tuple[int, int]] = []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            pair = _coerce_coord_pair(item)
            if pair is not None:
                out.append(pair)
    return out


def _normalize_keypress(value: Any) -> str:
    """OpenAI's ``keypress`` carries ``keys: ["CTRL", "C"]``. Anthropic's
    ``key`` carries ``text: "ctrl+c"``. Output the FERAL "+"-joined
    canonical form so :class:`GUIComputerUseSkill` can dispatch it
    through the same hotkey path."""
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        parts = []
        for item in value:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip().lower())
        return "+".join(parts)
    return ""


def normalize_action(raw: Any) -> Optional[NormalizedAction]:
    """Normalize one vendor action dict into a :class:`NormalizedAction`.

    Returns ``None`` if the input is unrecognisable. The driver
    intentionally errs on the side of ``None`` rather than fabricating
    an action; an unrecognised payload is a real failure mode the agent
    should learn from, not silently coerce.
    """
    if not isinstance(raw, Mapping):
        return None

    description = str(raw.get("description") or "")

    # FERAL VLM dialect — uses the `action` key.
    if "action" in raw and "type" not in raw:
        return _normalize_feral(raw, description)

    # Anthropic / OpenAI dialects — use the `type` key.
    if "type" in raw:
        return _normalize_vendor_type(raw, description)

    return None


def _normalize_feral(raw: Mapping[str, Any], description: str) -> Optional[NormalizedAction]:
    action_raw = str(raw.get("action") or "").strip().lower()
    if action_raw not in CANONICAL_ACTIONS:
        return None

    n = NormalizedAction(action=action_raw, provider="feral", description=description)
    if action_raw in ("click", "double_click", "right_click", "move"):
        try:
            n.x = int(raw.get("x") or 0)
            n.y = int(raw.get("y") or 0)
        except (TypeError, ValueError):
            return None
    elif action_raw == "type":
        n.text = str(raw.get("text") or "")
    elif action_raw == "key":
        n.keys = str(raw.get("keys") or "").strip().lower()
    elif action_raw == "scroll":
        n.direction = str(raw.get("direction") or "down").lower()
        try:
            n.amount = int(raw.get("amount") or 3)
        except (TypeError, ValueError):
            n.amount = 3
        if "x" in raw and "y" in raw:
            try:
                n.x = int(raw["x"])
                n.y = int(raw["y"])
            except (TypeError, ValueError):
                pass
    elif action_raw == "drag":
        n.path = _coerce_path(raw.get("path"))
        if not n.path:
            return None
    elif action_raw == "wait":
        try:
            n.duration_ms = int(raw.get("ms") or raw.get("duration") or 1000)
        except (TypeError, ValueError):
            n.duration_ms = 1000
    elif action_raw == "shell":
        n.command = str(raw.get("command") or "")
        if not n.command:
            return None
    elif action_raw == "done":
        n.summary = str(raw.get("summary") or "")
    elif action_raw == "failed":
        n.reason = str(raw.get("reason") or "")
    return n


def _normalize_vendor_type(raw: Mapping[str, Any], description: str) -> Optional[NormalizedAction]:
    """Handle both Anthropic and OpenAI ``type``-keyed actions.

    Anthropic uses ``coordinate: [x, y]`` and a ``computer_20241022`` /
    ``computer_20250124`` tool name; OpenAI's GA tool uses ``x``/``y``
    integers. We disambiguate by what's actually present in the payload
    rather than by a vendor flag — this keeps the driver robust to
    custom harnesses that mix shapes.
    """
    type_raw = str(raw.get("type") or "").strip().lower()

    feral_action = _ANTHROPIC_TYPE_TO_FERAL.get(type_raw) or _OPENAI_TYPE_TO_FERAL.get(type_raw)
    if not feral_action:
        return None

    is_anthropic_shape = "coordinate" in raw or "start_coordinate" in raw or "scroll_direction" in raw
    provider = "anthropic" if is_anthropic_shape else "openai"

    n = NormalizedAction(action=feral_action, provider=provider, description=description)

    if feral_action in ("click", "double_click", "right_click", "move"):
        coord = _coerce_coord_pair(raw.get("coordinate"))
        if coord is None:
            try:
                coord = (int(raw.get("x") or 0), int(raw.get("y") or 0))
            except (TypeError, ValueError):
                return None
        n.x, n.y = coord
        return n

    if feral_action == "type":
        n.text = str(raw.get("text") or "")
        return n

    if feral_action == "key":
        # Anthropic: {"type":"key", "text":"ctrl+c"} or hold_key with `duration`.
        # OpenAI:    {"type":"keypress", "keys":["CTRL","C"]}.
        if "keys" in raw:
            n.keys = _normalize_keypress(raw.get("keys"))
        else:
            n.keys = str(raw.get("text") or "").strip().lower()
        if not n.keys:
            return None
        if type_raw == "hold_key":
            try:
                n.duration_ms = int(float(raw.get("duration") or 0) * 1000)
            except (TypeError, ValueError):
                n.duration_ms = 0
        return n

    if feral_action == "scroll":
        # Anthropic: scroll_direction + scroll_amount + coordinate.
        # OpenAI:    direction + amount + (x,y) optional.
        n.direction = str(
            raw.get("scroll_direction")
            or raw.get("direction")
            or "down"
        ).lower()
        try:
            n.amount = int(raw.get("scroll_amount") or raw.get("amount") or 3)
        except (TypeError, ValueError):
            n.amount = 3
        coord = _coerce_coord_pair(raw.get("coordinate"))
        if coord is None and "x" in raw and "y" in raw:
            try:
                coord = (int(raw["x"]), int(raw["y"]))
            except (TypeError, ValueError):
                coord = None
        if coord is not None:
            n.x, n.y = coord
        return n

    if feral_action == "drag":
        # Anthropic ``left_click_drag`` carries two endpoints; OpenAI's
        # ``drag`` carries a full ``path``. Build a path either way.
        if "path" in raw:
            n.path = _coerce_path(raw.get("path"))
        else:
            start = _coerce_coord_pair(raw.get("start_coordinate"))
            end = _coerce_coord_pair(raw.get("coordinate"))
            n.path = [p for p in (start, end) if p is not None]
        if not n.path:
            return None
        return n

    if feral_action == "wait":
        # Anthropic: duration in seconds (float). OpenAI: ms.
        if "duration" in raw:
            try:
                n.duration_ms = int(float(raw["duration"]) * 1000)
            except (TypeError, ValueError):
                n.duration_ms = 1000
        else:
            try:
                n.duration_ms = int(raw.get("ms") or 1000)
            except (TypeError, ValueError):
                n.duration_ms = 1000
        return n

    if feral_action == "screenshot":
        return n

    return None


# ── Routing — IR → primitive ───────────────────────────────────────────


# Mapping from the canonical IR action to the gui_computer_use endpoint
# id we delegate to. Keeps the duplicate pyautogui calls in
# ``agentic_computer_use._do_*`` avoidable: the agentic loop normalizes
# via this driver and then calls ``GUIComputerUseSkill.execute(endpoint,
# args, vault)`` so all DPI / rate-limit / pyautogui code lives in one
# place.

GUI_ENDPOINT_FOR: Dict[str, str] = {
    "click": "mouse_click",
    "double_click": "mouse_double_click",
    "right_click": "mouse_right_click",
    "move": "mouse_move",
    "type": "type_text",
    "key": "key_press",
    "scroll": "scroll",
    "screenshot": "screenshot",
}


def gui_args_for(action: NormalizedAction) -> Dict[str, Any]:
    """Translate a NormalizedAction into the kwargs ``GUIComputerUseSkill``
    expects for the corresponding endpoint id."""
    if action.action in ("click", "double_click", "right_click", "move"):
        return {"x": int(action.x or 0), "y": int(action.y or 0)}
    if action.action == "type":
        return {"text": action.text}
    if action.action == "key":
        return {"keys": action.keys}
    if action.action == "scroll":
        out: Dict[str, Any] = {
            "direction": action.direction,
            "amount": int(action.amount),
        }
        if action.x is not None and action.y is not None:
            out["x"] = int(action.x)
            out["y"] = int(action.y)
        return out
    if action.action == "screenshot":
        return {}
    return {}


__all__ = [
    "NormalizedAction",
    "CANONICAL_ACTIONS",
    "GUI_ENDPOINT_FOR",
    "normalize_action",
    "gui_args_for",
]
