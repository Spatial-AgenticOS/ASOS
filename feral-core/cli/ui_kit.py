"""Shared CLI UI primitives — InquirerPy + Rich, with non-tty fallback.

Single source of truth for prompt UX across every ``feral`` subcommand
(``feral setup``, ``feral install``, ``feral key``, ``feral access``,
``feral doctor``). Call sites never touch InquirerPy or Rich directly,
so the brand chrome (raccoon emoji, brand colour, panels) stays
consistent and the non-tty fallback path is exercised in one place.

Truthfulness rules
------------------
* When ``InquirerPy`` is not installed OR ``stdin``/``stdout`` is not a
  TTY, every prompt falls back to plain ``input``/``getpass`` and the
  prompt label is annotated so the operator can see they're in the
  silent path. We never pretend to mask characters when we cannot.
* ``brand_panel`` and ``banner_line`` degrade to plain text when Rich
  is unavailable; they never raise.
* ``warn_non_interactive_setup_hint`` prints the exact ``ssh -t``
  invocation needed when the wizard is launched without a controlling
  TTY, instead of silently falling back to a degraded UX.

Asyncio nested-loop fix
-----------------------
The wizard runs inside ``asyncio.run(_run_async())`` so every prompt
call lands while an event loop is already running. ``prompt_toolkit``
(which InquirerPy wraps) detects the running loop and returns a
coroutine from ``Application.run()`` instead of blocking — that broke
v2026.5.22 where the prompts silently fell back to the typed numeric
fallback. ``_run_inquirer_safely`` detects this case and runs the
prompt in a worker thread that has no event loop of its own, so
prompt_toolkit's normal blocking path works. When called from a sync
context (no running loop) we bypass the thread entirely.
"""

from __future__ import annotations

import asyncio
import getpass
import logging
import sys
import threading
from typing import Any, Callable, Optional, Sequence, Union

logger = logging.getLogger("feral.cli.ui_kit")

try:
    from rich.console import Console
    from rich.panel import Panel

    _RICH_AVAILABLE = True
except Exception:  # pragma: no cover - rich is a hard dep but guard anyway
    Console = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    _RICH_AVAILABLE = False

try:
    from InquirerPy import inquirer  # type: ignore
    from InquirerPy.base.control import Choice  # type: ignore

    _INQUIRER_AVAILABLE = True
except Exception:  # pragma: no cover - InquirerPy is the new dep; allow tests to run without it
    inquirer = None  # type: ignore[assignment]
    Choice = None  # type: ignore[assignment]
    _INQUIRER_AVAILABLE = False


BRAND_EMOJI = "🦝"
BRAND_COLOR = "cyan"


# ---------------------------------------------------------------------------
# Console / TTY helpers
# ---------------------------------------------------------------------------


def _is_interactive() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def is_interactive() -> bool:
    """Public alias — used by callers that want to gate features by TTY."""
    return _is_interactive()


def is_inquirer_available() -> bool:
    return bool(_INQUIRER_AVAILABLE)


class _FallbackConsole:
    def print(self, *args, **kwargs) -> None:
        text_out = " ".join(str(a) for a in args)
        sys.stdout.write(text_out + "\n")
        sys.stdout.flush()


def get_console():
    if _RICH_AVAILABLE:
        return Console()
    return _FallbackConsole()


# ---------------------------------------------------------------------------
# Brand chrome
# ---------------------------------------------------------------------------


def brand_panel(
    title: str,
    body: str = "",
    *,
    console=None,
    border_style: str = BRAND_COLOR,
) -> None:
    """Render a Rich panel with the raccoon emoji prefix.

    Falls back to a plain hr-bracketed block when Rich is unavailable
    so callers can use this primitive everywhere without conditionals.
    """
    console = console or get_console()
    titled = f"{BRAND_EMOJI}  {title}"
    if _RICH_AVAILABLE and Panel is not None:
        console.print(Panel.fit(body or "", title=titled, border_style=border_style))
        return
    bar = "─" * max(20, len(titled) + 4)
    console.print(bar)
    console.print(titled)
    if body:
        console.print(bar)
        console.print(body)
    console.print(bar)


def banner_line(
    message: str,
    *,
    style: str = BRAND_COLOR,
    console=None,
) -> None:
    """Single-line raccoon-prefixed status message."""
    console = console or get_console()
    if _RICH_AVAILABLE:
        console.print(f"[{style}]{BRAND_EMOJI}[/]  {message}")
    else:
        console.print(f"{BRAND_EMOJI}  {message}")


# ---------------------------------------------------------------------------
# Asyncio nested-loop shim
# ---------------------------------------------------------------------------


def _run_inquirer_safely(builder: Callable[[], Any]) -> Any:
    """Call an InquirerPy prompt's ``.execute()`` in a context where
    prompt_toolkit will actually block.

    The wizard runs inside ``asyncio.run(_run_async())``, so when a
    step calls ``inquirer.X(...).execute()`` prompt_toolkit detects the
    already-running loop and returns a coroutine instead of blocking
    (and emits ``RuntimeWarning: coroutine 'Application.run_async' was
    never awaited``). To get the normal blocking semantics back we run
    the builder in a worker thread that has no event loop bound to it.
    The main thread then ``done.wait()``s the worker — that intentionally
    blocks the asyncio loop, which is fine because the wizard step is
    the only thing happening at that point.
    """
    try:
        asyncio.get_running_loop()
        nested = True
    except RuntimeError:
        nested = False

    if not nested:
        return builder()

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            result["v"] = builder()
        except BaseException as exc:  # noqa: BLE001 — propagate every exception type
            error["e"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_worker, name="feral-ui-prompt", daemon=True)
    worker.start()
    done.wait()
    if "e" in error:
        raise error["e"]
    return result.get("v")


# ---------------------------------------------------------------------------
# Choice normalisation
# ---------------------------------------------------------------------------


ChoiceLike = Union[str, dict, Any]


def _normalise_choices(choices: Sequence[ChoiceLike]) -> list:
    """Map our loose choice shapes into either InquirerPy Choice objects
    (when available) or plain dicts the fallback path can read."""
    out: list = []
    for c in choices:
        if isinstance(c, str):
            if _INQUIRER_AVAILABLE:
                out.append(Choice(value=c, name=c))
            else:
                out.append({"name": c, "value": c})
        elif isinstance(c, dict):
            name = c.get("name") or str(c.get("value", ""))
            value = c.get("value", name)
            if _INQUIRER_AVAILABLE:
                out.append(
                    Choice(value=value, name=name, enabled=bool(c.get("enabled", False)))
                )
            else:
                out.append({"name": name, "value": value})
        else:
            # Already a Choice or arbitrary object — pass through.
            out.append(c)
    return out


def _fallback_pairs(choices: Sequence[ChoiceLike]) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    for c in choices:
        if isinstance(c, str):
            pairs.append((c, c))
        elif isinstance(c, dict):
            name = c.get("name") or str(c.get("value", ""))
            value = c.get("value", name)
            pairs.append((str(name), value))
        else:
            name = getattr(c, "name", None) or str(getattr(c, "value", c))
            value = getattr(c, "value", c)
            pairs.append((str(name), value))
    return pairs


def _fallback_select(
    message: str,
    choices: Sequence[ChoiceLike],
    *,
    default: Any = None,
) -> Any:
    pairs = _fallback_pairs(choices)
    sys.stdout.write(message + "\n")
    for i, (name, _) in enumerate(pairs, start=1):
        sys.stdout.write(f"  {i}. {name}\n")
    default_label = ""
    default_idx = None
    if default is not None:
        for i, (_, value) in enumerate(pairs, start=1):
            if value == default:
                default_idx = i
                default_label = f" [{i}]"
                break
    while True:
        sys.stdout.write(f"  Choose{default_label}: ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "":
            raise EOFError("stdin closed during select")
        line = line.strip()
        if line == "" and default_idx is not None:
            return pairs[default_idx - 1][1]
        if line.isdigit():
            idx = int(line) - 1
            if 0 <= idx < len(pairs):
                return pairs[idx][1]
        for name, value in pairs:
            if line.lower() == str(name).lower() or line.lower() == str(value).lower():
                return value
        sys.stdout.write("  Invalid choice — try again.\n")


def _normalise_default_for_checkbox(default: Any, choices: Sequence[ChoiceLike]) -> list:
    """Mark the matching choice as enabled so the user lands on it pre-marked."""
    if default is None:
        return _normalise_choices(choices)
    out: list = []
    for c in choices:
        value = c if isinstance(c, str) else (c.get("value") if isinstance(c, dict) else c)
        name = (
            c
            if isinstance(c, str)
            else (c.get("name") or str(c.get("value", ""))) if isinstance(c, dict) else str(c)
        )
        is_default = value == default
        if _INQUIRER_AVAILABLE:
            out.append(Choice(value=value, name=name, enabled=is_default))
        else:
            out.append({"name": name, "value": value, "enabled": is_default})
    return out


# ---------------------------------------------------------------------------
# Public prompts
# ---------------------------------------------------------------------------


_SELECT_INSTRUCTION = "↑/↓ navigate · space to mark · enter to confirm"
_FUZZY_INSTRUCTION = "type to filter · ↑/↓ navigate · space to mark · enter to confirm"


def _validate_single_selection(result) -> bool:
    return isinstance(result, list) and len(result) == 1


def select(
    message: str,
    choices: Sequence[ChoiceLike],
    *,
    default: Any = None,
    instruction: str = _SELECT_INSTRUCTION,
) -> Any:
    """Single-pick from a list using arrow keys + space + enter.

    Implemented on top of InquirerPy's ``checkbox`` with a
    ``len(result) == 1`` validator so the user marks exactly one item
    with space, then confirms with enter (the user's preferred UX —
    they want to *see* their pick before committing instead of
    enter-on-cursor-position semantics). Falls back to a numeric typed
    prompt off-tty.
    """
    if _INQUIRER_AVAILABLE and _is_interactive():
        try:
            normalised = _normalise_default_for_checkbox(default, choices)

            def _build():
                return inquirer.checkbox(  # type: ignore[union-attr]
                    message=message,
                    choices=normalised,
                    instruction=instruction,
                    qmark=BRAND_EMOJI,
                    amark=BRAND_EMOJI,
                    pointer="❯",
                    enabled_symbol="[*]",
                    disabled_symbol="[ ]",
                    validate=_validate_single_selection,
                    invalid_message="press space to mark exactly one option, then enter",
                    transformer=lambda r: r[0] if isinstance(r, list) and r else "",
                ).execute()

            picked = _run_inquirer_safely(_build)
            if isinstance(picked, list) and picked:
                return picked[0]
            return picked
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # pragma: no cover - last-ditch defensive log
            logger.debug("ui_kit.select InquirerPy path failed: %r", exc)
    return _fallback_select(message, choices, default=default)


def fuzzy_select(
    message: str,
    choices: Sequence[ChoiceLike],
    *,
    default: Any = None,
    instruction: str = _FUZZY_INSTRUCTION,
) -> Any:
    """Type-to-filter single-pick (e.g. for hundreds of model ids).

    Same UX contract as ``select``: arrows navigate, space marks the
    choice, enter confirms. Implemented on top of ``inquirer.fuzzy``
    with ``multiselect=True`` + a single-selection validator.
    """
    if _INQUIRER_AVAILABLE and _is_interactive():
        try:
            normalised = _normalise_default_for_checkbox(default, choices)

            def _build():
                return inquirer.fuzzy(  # type: ignore[union-attr]
                    message=message,
                    choices=normalised,
                    instruction=instruction,
                    qmark=BRAND_EMOJI,
                    amark=BRAND_EMOJI,
                    border=True,
                    multiselect=True,
                    validate=_validate_single_selection,
                    invalid_message="press space to mark exactly one option, then enter",
                    transformer=lambda r: r[0] if isinstance(r, list) and r else "",
                ).execute()

            picked = _run_inquirer_safely(_build)
            if isinstance(picked, list) and picked:
                return picked[0]
            return picked
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # pragma: no cover
            logger.debug("ui_kit.fuzzy_select InquirerPy path failed: %r", exc)
    return _fallback_select(message, choices, default=default)


def password(
    message: str,
    *,
    mask: str = "*",
    validate: Optional[Callable[[str], bool]] = None,
    allow_empty: bool = False,
) -> str:
    """Masked password prompt.

    InquirerPy / prompt_toolkit show one ``mask`` character per typed
    character so the operator gets visible feedback that the paste
    landed. Falls back to ``getpass.getpass`` (silent — same as the
    legacy behaviour) when the library is unavailable or stdin is not
    a TTY. The fallback annotates the prompt label so the operator can
    see they're in the silent path.
    """

    def _final_validate(raw: str) -> bool:
        if not allow_empty and not raw:
            return False
        if validate is not None:
            try:
                return bool(validate(raw))
            except Exception:
                return False
        return True

    if _INQUIRER_AVAILABLE and _is_interactive():
        try:

            def _build():
                return inquirer.secret(  # type: ignore[union-attr]
                    message=message,
                    qmark=BRAND_EMOJI,
                    amark=BRAND_EMOJI,
                    transformer=lambda r: mask * len(r) if r else "",
                    validate=_final_validate,
                    invalid_message="value cannot be empty",
                ).execute()

            return _run_inquirer_safely(_build)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # pragma: no cover
            logger.debug("ui_kit.password InquirerPy path failed: %r", exc)

    label = f"{message} (silent — non-interactive shell)"
    while True:
        try:
            value = getpass.getpass(label + ": ")
        except (EOFError, KeyboardInterrupt):
            raise
        if _final_validate(value):
            return value
        sys.stdout.write("  value cannot be empty — try again.\n")


def confirm(message: str, *, default: bool = False) -> bool:
    """Yes/no with a default."""
    if _INQUIRER_AVAILABLE and _is_interactive():
        try:

            def _build():
                return bool(
                    inquirer.confirm(  # type: ignore[union-attr]
                        message=message,
                        default=default,
                        qmark=BRAND_EMOJI,
                        amark=BRAND_EMOJI,
                    ).execute()
                )

            return _run_inquirer_safely(_build)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # pragma: no cover
            logger.debug("ui_kit.confirm InquirerPy path failed: %r", exc)
    suffix = "Y/n" if default else "y/N"
    while True:
        sys.stdout.write(f"{message} [{suffix}]: ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "":
            return default
        line = line.strip().lower()
        if line == "":
            return default
        if line in ("y", "yes", "true", "1"):
            return True
        if line in ("n", "no", "false", "0"):
            return False
        sys.stdout.write("  Please answer yes or no.\n")


def text(
    message: str,
    *,
    default: str = "",
    validate: Optional[Callable[[str], bool]] = None,
    instruction: str = "",
    allow_empty: bool = True,
) -> str:
    """Free-text input."""

    def _final_validate(raw: str) -> bool:
        if not allow_empty and not raw:
            return False
        if validate is not None:
            try:
                return bool(validate(raw))
            except Exception:
                return False
        return True

    if _INQUIRER_AVAILABLE and _is_interactive():
        try:

            def _build():
                return inquirer.text(  # type: ignore[union-attr]
                    message=message,
                    default=default,
                    qmark=BRAND_EMOJI,
                    amark=BRAND_EMOJI,
                    validate=_final_validate,
                    instruction=instruction,
                    invalid_message="value cannot be empty",
                ).execute()

            return _run_inquirer_safely(_build)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # pragma: no cover
            logger.debug("ui_kit.text InquirerPy path failed: %r", exc)
    suffix = f" [{default}]" if default else ""
    while True:
        sys.stdout.write(f"{message}{suffix}: ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if line == "":
            raise EOFError("stdin closed during text input")
        stripped = line.strip()
        if not stripped and default:
            return default
        if _final_validate(stripped):
            return stripped
        sys.stdout.write("  value cannot be empty — try again.\n")


def warn_non_interactive_setup_hint(console=None) -> None:
    """Print a one-line hint when an interactive command is launched
    without a controlling TTY (e.g. ``ssh host feral setup`` instead of
    ``ssh -t host feral setup``).
    """
    if _is_interactive():
        return
    console = console or get_console()
    hint = (
        "Interactive setup needs a real terminal. "
        "If you're SSH'd in, re-run with `ssh -t <host> feral setup`. "
        "For headless setup use `feral config set …`."
    )
    if _RICH_AVAILABLE:
        console.print(f"[{BRAND_COLOR}]{BRAND_EMOJI}[/]  {hint}")
    else:
        console.print(f"{BRAND_EMOJI}  {hint}")


__all__ = [
    "BRAND_EMOJI",
    "BRAND_COLOR",
    "select",
    "fuzzy_select",
    "password",
    "confirm",
    "text",
    "brand_panel",
    "banner_line",
    "get_console",
    "is_inquirer_available",
    "is_interactive",
    "warn_non_interactive_setup_hint",
]
