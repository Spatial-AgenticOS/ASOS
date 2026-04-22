"""Shared prompt + table helpers used by every step.

Design rules:

* ``ask_choice`` never rejects a valid user input because of a typo
  or capitalisation mismatch. It accepts the canonical id, any
  declared alias, a 1-based index, or an unambiguous substring. When
  multiple options match it re-prompts with the disambiguation list
  instead of silently picking one.
* ``ask_text`` is free-text with a sane default. Empty input accepts
  the default. Leading/trailing whitespace is stripped.
* ``confirm`` is yes/no with a default.
* ``render_table`` uses Rich when available; falls back to a plain
  markdown-ish renderer so headless environments still see the data.
* ``STATUS_READY`` / ``STATUS_NEEDS_KEY`` / ``STATUS_UNREACHABLE`` are
  the three states the provider table renders.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table

    _RICH_AVAILABLE = True
except Exception:  # pragma: no cover - rich is a hard dep but guard anyway
    _RICH_AVAILABLE = False


STATUS_READY = "ready"
STATUS_NEEDS_KEY = "needs_api_key"
STATUS_UNREACHABLE = "unreachable"
STATUS_UNAVAILABLE = "unavailable"


def get_console():
    if _RICH_AVAILABLE:
        return Console()
    return _FallbackConsole()


class _FallbackConsole:
    def print(self, *args, **kwargs) -> None:
        text = " ".join(str(a) for a in args)
        # Strip any markup tags the caller might have passed.
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


@dataclass(frozen=True)
class Option:
    """A picker entry — id + human label + optional aliases + status.

    Status is rendered in the side-by-side table but does *not* block
    selection. The wizard explicitly wants to allow users to pick
    providers that show unreachable so they can re-probe after
    entering a key or starting the local server.
    """

    id: str
    label: str
    aliases: tuple[str, ...] = ()
    status: str = ""  # "ready" / "needs_api_key" / "unreachable" / ""
    hint: str = ""


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def resolve_option(text: str, options: Sequence[Option]) -> Optional[Option]:
    """Map a user-typed string to an :class:`Option` using the same
    precedence the catalog uses: canonical id → label → alias →
    numeric index → unambiguous substring.

    Returns ``None`` on ambiguity or empty input so the caller can
    re-prompt.
    """
    norm = _normalize(text)
    if not norm:
        return None

    # 1-based numeric index
    if norm.isdigit():
        idx = int(norm) - 1
        if 0 <= idx < len(options):
            return options[idx]
        return None

    for opt in options:
        if norm == _normalize(opt.id):
            return opt
        if norm == _normalize(opt.label):
            return opt
        if any(norm == _normalize(a) for a in opt.aliases):
            return opt

    # Substring match — unambiguous only.
    hits = []
    for opt in options:
        needles = [opt.id, opt.label, *opt.aliases]
        if any(norm in _normalize(n) for n in needles):
            hits.append(opt)
    if len(hits) == 1:
        return hits[0]
    return None


def ask_choice(
    prompt: str,
    options: Sequence[Option],
    *,
    default: Optional[str] = None,
    console=None,
) -> Option:
    """Prompt the user for one of the given options, retrying on bad input.

    Empty input accepts ``default`` when supplied. Typing ``back`` /
    ``quit`` raises :class:`BackNavigation` / :class:`QuitNavigation`
    so the state machine can handle navigation centrally.
    """
    console = console or get_console()
    default_opt: Optional[Option] = None
    if default:
        default_opt = next((o for o in options if o.id == default), None)

    while True:
        default_display = f" [{default_opt.label}]" if default_opt else ""
        raw = _prompt_raw(f"{prompt}{default_display}", console)
        if raw == "":
            if default_opt is not None:
                return default_opt
            console.print("[yellow]Please type a choice.[/]" if _RICH_AVAILABLE else "Please type a choice.")
            continue
        if raw.lower() in ("back", "b"):
            raise BackNavigation()
        if raw.lower() in ("quit", "q", "exit"):
            raise QuitNavigation()

        hit = resolve_option(raw, options)
        if hit is not None:
            return hit

        # Suggest candidates if the substring matched multiple.
        norm = _normalize(raw)
        candidates = [
            o for o in options
            if norm in _normalize(o.id) or norm in _normalize(o.label)
            or any(norm in _normalize(a) for a in o.aliases)
        ]
        if candidates:
            names = ", ".join(c.label for c in candidates)
            console.print(f"Ambiguous — did you mean: {names}? Please type one exactly.")
        else:
            console.print(f"'{raw}' isn't a valid choice. Try again (type 'back' to go back).")


def ask_text(
    prompt: str,
    *,
    default: str = "",
    allow_empty: bool = True,
    secret: bool = False,
    console=None,
) -> str:
    """Free-text input with back/quit support."""
    console = console or get_console()
    while True:
        default_display = f" [{default}]" if default else ""
        raw = _prompt_raw(f"{prompt}{default_display}", console, password=secret)
        if raw == "" and default:
            return default
        if raw.lower() in ("back", "b"):
            raise BackNavigation()
        if raw.lower() in ("quit", "q", "exit"):
            raise QuitNavigation()
        if raw == "" and not allow_empty:
            console.print("[yellow]This field can't be empty.[/]" if _RICH_AVAILABLE else "This field can't be empty.")
            continue
        return raw


def confirm(prompt: str, *, default: bool = False, console=None) -> bool:
    console = console or get_console()
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = _prompt_raw(f"{prompt} [{suffix}]", console)
        if raw == "":
            return default
        if raw.lower() in ("back", "b"):
            raise BackNavigation()
        if raw.lower() in ("quit", "q", "exit"):
            raise QuitNavigation()
        if raw.lower() in ("y", "yes", "true", "1"):
            return True
        if raw.lower() in ("n", "no", "false", "0"):
            return False
        console.print("Please answer yes or no.")


def _prompt_raw(prompt: str, console, *, password: bool = False) -> str:
    try:
        if _RICH_AVAILABLE:
            return Prompt.ask(prompt, password=password, show_default=False).strip()
    except EOFError:
        raise QuitNavigation()

    # Plain fallback.
    try:
        if password:
            import getpass
            return getpass.getpass(prompt + ": ").strip()
        sys.stdout.write(prompt + ": ")
        sys.stdout.flush()
        return sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        raise QuitNavigation()


# ----------------------------------------------------------------------
# Table rendering
# ----------------------------------------------------------------------


def render_provider_table(
    title: str,
    options: Sequence[Option],
    *,
    console=None,
    extra_columns: Optional[dict[str, dict[str, str]]] = None,
) -> None:
    """Render the side-by-side provider table with ready/needs-key/unreachable."""
    console = console or get_console()
    extra_columns = extra_columns or {}
    if _RICH_AVAILABLE:
        table = Table(title=title, show_lines=False)
        table.add_column("#", style="dim", justify="right")
        table.add_column("Provider", style="bold")
        table.add_column("Status")
        if extra_columns:
            table.add_column("Notes")
        for i, opt in enumerate(options, start=1):
            status = _pretty_status(opt.status)
            row = [str(i), opt.label, status]
            if extra_columns:
                note = extra_columns.get(opt.id, {}).get("note", opt.hint or "")
                row.append(note)
            table.add_row(*row)
        console.print(table)
        return

    # Fallback plain renderer
    console.print(title)
    for i, opt in enumerate(options, start=1):
        console.print(f"  {i}. {opt.label} — {_pretty_status(opt.status)}  {opt.hint}")


def _pretty_status(status: str) -> str:
    mapping = {
        STATUS_READY: "[green]ready[/]" if _RICH_AVAILABLE else "ready",
        STATUS_NEEDS_KEY: "[yellow]needs API key[/]" if _RICH_AVAILABLE else "needs API key",
        STATUS_UNREACHABLE: "[red]unreachable[/]" if _RICH_AVAILABLE else "unreachable",
        STATUS_UNAVAILABLE: "[dim]unavailable[/]" if _RICH_AVAILABLE else "unavailable",
        "": "",
    }
    return mapping.get(status, status)


# ----------------------------------------------------------------------
# Navigation exceptions
# ----------------------------------------------------------------------


class BackNavigation(Exception):
    """Raised by any prompt when the user types 'back'."""


class QuitNavigation(Exception):
    """Raised by any prompt when the user types 'quit'."""


class SkipStep(Exception):
    """A step raises this to tell the state machine to move on without persisting data."""
