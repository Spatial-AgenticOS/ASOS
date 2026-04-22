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
    elif desc.provider_id in ("ollama", "lmstudio"):
        # Local providers — flag the user if the server isn't up yet.
        status = statuses.get(desc.provider_id)
        if status and not status.reachable:
            console.print(
                f"  [yellow]⚠[/] {desc.display_name} is not responding at {desc.default_base_url}"
            )
            console.print("     Start the server, then run `feral setup` again to re-probe.")


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
        console.print(f"[bold]Step 2 · Model[/]")
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
