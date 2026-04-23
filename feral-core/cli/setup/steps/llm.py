"""Provider + model selection step.

Reads the live ProviderCatalog, renders a side-by-side "ready vs
needs-key vs unreachable" table, accepts fuzzy provider names, lets
the user type any model id even if it's newer than the bundled
catalog.
"""

from __future__ import annotations

import os
from typing import Iterable

from providers.catalog import (
    ProviderCatalog,
    ProviderStatus,
    get_shared_catalog,
)

from ..helpers import (
    STATUS_NEEDS_KEY,
    STATUS_READY,
    STATUS_UNREACHABLE,
    Option,
    ask_choice,
    ask_text,
    confirm,
    get_console,
    render_provider_table,
    _RICH_AVAILABLE,
)
from ..state import WizardState


async def run_provider_step(state: WizardState) -> None:
    console = get_console()
    catalog = _catalog(state)

    # Probe every provider so the table shows reachable state. This is
    # parallel under a single refresh_all but we call probe() per-id so
    # the network results can differ (Ollama reachable, OpenAI not).
    statuses = await _probe_all(catalog)
    options = _build_options(catalog, statuses)
    extra_notes = _build_notes(catalog, statuses)

    if _RICH_AVAILABLE:
        console.print()
        console.print("[bold]Step 1 · LLM Provider[/]")
        console.print("Pick the provider you want FERAL's brain to talk to. Local providers")
        console.print("show [green]ready[/] when detected. Cloud providers show [yellow]needs API key[/]")
        console.print("until you enter one — you can still select them and add the key next.")
    else:
        console.print("\nStep 1 · LLM Provider")

    render_provider_table("Available providers", options, extra_columns=extra_notes)

    default_id = state.get_setting("llm", "provider") or _default_choice(options)
    chosen = ask_choice("Choose a provider", options, default=default_id)
    state.set_setting("llm", "provider", chosen.id)

    desc = catalog.get_descriptor(chosen.id)
    if desc is None:
        return

    if desc.default_base_url and not state.get_setting("llm", "base_url"):
        state.set_setting("llm", "base_url", desc.default_base_url)

    # Cloud providers: capture API key unless one is already present
    # (either in env or in the vault-backed credentials.json we loaded).
    if desc.requires_api_key:
        env_var = desc.credential_env_var
        existing = (
            os.environ.get(env_var, "")
            or state.credentials.get(env_var, "")
        )
        if existing:
            keep = confirm(
                f"  Use existing {env_var} from your environment / credentials?",
                default=True,
            )
            if not keep:
                existing = ""
        if not existing:
            key = ask_text(
                f"  Enter your {desc.display_name} API key",
                allow_empty=False,
                secret=True,
            )
            state.set_credential(env_var, key)
            os.environ[env_var] = key
            catalog.configure(chosen.id, api_key=key)

        # Re-probe to flip the status from needs_key → ready.
        updated = await catalog.probe(chosen.id)
        if updated.reachable:
            console.print(f"  [green]✓[/] {desc.display_name} reachable")
        else:
            msg = updated.error or "unreachable"
            console.print(f"  [yellow]note:[/] probe said: {msg} — you can continue and re-probe later.")
    elif desc.provider_id == "ollama":
        status = statuses.get(desc.provider_id)
        if not (status and status.reachable):
            await _handle_ollama_unreachable(console)
        else:
            # Reachable but maybe zero models — offer to pull one.
            cached = await catalog.list_models(chosen.id, live=True, force=True)
            if not cached.models:
                await _handle_ollama_no_models(catalog, console)
    elif desc.provider_id == "lmstudio":
        status = statuses.get(desc.provider_id)
        if not (status and status.reachable):
            _show_lmstudio_instructions(console)
        else:
            cached = await catalog.list_models(chosen.id, live=True, force=True)
            if not cached.models:
                _show_lmstudio_no_model(console)


async def run_model_step(state: WizardState) -> None:
    console = get_console()
    catalog = _catalog(state)
    provider_id = state.get_setting("llm", "provider")
    if not provider_id:
        return
    desc = catalog.get_descriptor(provider_id)
    if desc is None:
        return

    try:
        cached = await catalog.list_models(provider_id, live=True, force=True)
    except Exception:
        cached = await catalog.list_models(provider_id, live=False)
    models = list(cached.models)

    if _RICH_AVAILABLE:
        console.print()
        console.print("[bold]Step 2 · Model[/]")
        console.print(
            f"Discovered {len(models)} models for {desc.display_name} "
            f"(source: {cached.source})."
        )

    # Show the first 25 models as a quick reference, then accept any input.
    if models:
        preview = models[:25]
        for i, model in enumerate(preview, start=1):
            console.print(f"  {i:>3}. {model}")
        if len(models) > len(preview):
            console.print(f"  ... and {len(models) - len(preview)} more.")
    else:
        console.print(
            "  (Could not fetch a live list — type the exact model name for this provider.)"
        )

    default = state.get_setting("llm", "model") or desc.default_model or (models[0] if models else "")

    while True:
        raw = ask_text(
            "Which model? (paste the id or pick a number above)",
            default=default,
            allow_empty=False,
        )
        # Numeric picker shortcut.
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(models):
                raw = models[idx]
            else:
                console.print("  number out of range")
                continue
        state.set_setting("llm", "model", raw)
        break


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _catalog(state: WizardState) -> ProviderCatalog:
    # Cache on the state so every step in a single run shares one catalog.
    cached = getattr(state, "_catalog", None)
    if cached is not None:
        return cached
    cat = get_shared_catalog()
    setattr(state, "_catalog", cat)
    return cat


async def _probe_all(catalog: ProviderCatalog) -> dict[str, ProviderStatus]:
    out: dict[str, ProviderStatus] = {}
    for desc in catalog.list_providers():
        try:
            out[desc.provider_id] = await catalog.probe(desc.provider_id)
        except Exception:
            out[desc.provider_id] = catalog.status_for(desc.provider_id)
    return out


def _build_options(
    catalog: ProviderCatalog, statuses: dict[str, ProviderStatus]
) -> list[Option]:
    options: list[Option] = []
    for desc in catalog.list_providers():
        status = statuses.get(desc.provider_id)
        if desc.supports_local:
            if status and status.reachable:
                ui_status = STATUS_READY
            else:
                ui_status = STATUS_UNREACHABLE
        else:
            if status and status.configured and status.reachable:
                ui_status = STATUS_READY
            elif desc.requires_api_key and not (status and status.configured):
                ui_status = STATUS_NEEDS_KEY
            else:
                ui_status = STATUS_READY if (status and status.reachable) else STATUS_UNREACHABLE
        options.append(
            Option(
                id=desc.provider_id,
                label=desc.display_name,
                aliases=desc.aliases,
                status=ui_status,
                hint=desc.notes,
            )
        )
    return options


def _build_notes(
    catalog: ProviderCatalog, statuses: dict[str, ProviderStatus]
) -> dict[str, dict[str, str]]:
    notes: dict[str, dict[str, str]] = {}
    for desc in catalog.list_providers():
        status = statuses.get(desc.provider_id)
        snippets: list[str] = []
        if desc.supports_local:
            snippets.append(f"local @ {desc.default_base_url}")
        elif desc.credential_env_var:
            snippets.append(f"env: {desc.credential_env_var}")
        if status and status.error:
            snippets.append(f"err: {status.error[:40]}")
        notes[desc.provider_id] = {"note": " · ".join(snippets)}
    return notes


def _default_choice(options: Iterable[Option]) -> str:
    # Prefer a local-ready provider; else the first non-unreachable cloud.
    ordered = list(options)
    for opt in ordered:
        if opt.status == STATUS_READY and "local" in opt.label.lower():
            return opt.id
    for opt in ordered:
        if opt.status == STATUS_READY:
            return opt.id
    for opt in ordered:
        if opt.status == STATUS_NEEDS_KEY:
            return opt.id
    return ordered[0].id if ordered else ""


# ----------------------------------------------------------------------
# Local provider assistance
# ----------------------------------------------------------------------


async def _handle_ollama_unreachable(console) -> None:
    from ..local_providers import OLLAMA_INSTALL_HINT, ollama_cli_installed

    console.print()
    console.print(
        "[yellow]Ollama isn't responding at http://localhost:11434.[/]"
        if _RICH_AVAILABLE else
        "Ollama isn't responding at http://localhost:11434."
    )
    if not ollama_cli_installed():
        for line in OLLAMA_INSTALL_HINT.splitlines():
            console.print(f"  {line}")
        return
    console.print("  `ollama` is on your PATH but the server isn't serving.")
    console.print("  Start it with: ollama serve")
    console.print("  Then re-run `feral setup` to continue.")


async def _handle_ollama_no_models(catalog, console) -> None:
    from ..helpers import ask_text, confirm
    from ..local_providers import STARTER_OLLAMA_MODELS, ollama_pull_model

    console.print("  Ollama is running but no models are installed yet.")
    if not confirm("  Pull a starter model now?", default=True):
        return
    options_text = ", ".join(STARTER_OLLAMA_MODELS)
    console.print(f"  Suggested: {options_text}")
    choice = ask_text(
        "  Model to pull",
        default=STARTER_OLLAMA_MODELS[0],
        allow_empty=False,
    )
    console.print(f"  Running `ollama pull {choice}` — streaming progress...")
    try:
        code = await ollama_pull_model(choice, on_line=lambda line: console.print(f"    {line}"))
    except Exception as exc:
        console.print(f"  [red]pull failed:[/] {exc}" if _RICH_AVAILABLE else f"  pull failed: {exc}")
        return
    if code == 0:
        console.print(f"  [green]✓[/] pulled {choice}" if _RICH_AVAILABLE else f"  pulled {choice}")
        # Refresh cache so the model step sees it.
        try:
            await catalog.list_models("ollama", live=True, force=True)
        except Exception:
            pass
    else:
        console.print(f"  [red]ollama pull exited with code {code}[/]" if _RICH_AVAILABLE else
                      f"  ollama pull exited with code {code}")


def _show_lmstudio_instructions(console) -> None:
    from ..local_providers import LMSTUDIO_INSTRUCTIONS

    console.print()
    for line in LMSTUDIO_INSTRUCTIONS.splitlines():
        console.print(f"  {line}")


def _show_lmstudio_no_model(console) -> None:
    console.print("  LM Studio is running but no model is loaded.")
    console.print("  Open LM Studio → pick a model → Start the local server.")
    console.print("  Then re-run `feral setup`.")
