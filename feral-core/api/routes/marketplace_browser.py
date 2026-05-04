"""Marketplace and browser control HTTP endpoints."""

from fastapi import APIRouter

from api.state import state

router = APIRouter()


# ─────────────────────────────────────────────
# Marketplace API
# ─────────────────────────────────────────────


@router.get("/api/marketplace/search")
async def marketplace_search(q: str = ""):
    """Search the skill marketplace."""
    if not state.marketplace:
        return {"results": []}
    results = await state.marketplace.search(q)
    return {"results": results}


@router.get("/api/marketplace/catalog")
async def marketplace_catalog(kind: str = "skill", q: str = "", sort: str = "newest"):
    """Browse the remote registry catalog, partitioned by kind.

    kind ∈ {"skill", "daemon", "mcp"}. Proxies to the configured
    ``FERAL_REGISTRY_URL`` (default https://registry.feral.sh) so the
    Settings UI has a single, stable endpoint across install targets.

    Walks the fallback URL list (see ``cli.publish.registry_base_urls``)
    on connection / DNS failures so a user whose network can't resolve
    the primary host (e.g. IPv6-only AAAA records) still reaches the
    registry via the direct Fly URL.
    """
    import httpx

    from cli.publish import registry_base_urls

    bases = registry_base_urls()
    last_error: Exception | None = None
    last_status: int | None = None
    for base in bases:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{base}/api/v1/catalog",
                    params={"kind": kind, "q": q, "sort": sort},
                )
                if resp.status_code != 200:
                    last_status = resp.status_code
                    continue
                data = resp.json()
                items = data.get("items") or data.get("results") or []
                return {
                    "items": items,
                    "kind": kind,
                    "source": base,
                    "tried": bases,
                }
        except Exception as exc:
            last_error = exc
            continue

    if last_error is not None:
        return {
            "items": [],
            "error": f"registry unreachable: {last_error}",
            "tried": bases,
        }
    return {
        "items": [],
        "error": f"registry returned {last_status}",
        "tried": bases,
    }


@router.post("/api/marketplace/install")
async def marketplace_install(body: dict):
    """Install an item from the marketplace.

    Accepts both the legacy shape ``{skill_id, version?, source_url?}`` and
    the new kind-aware shape ``{kind, id}`` used by the rewritten Settings
    UI. When ``kind`` is provided we delegate to the remote-registry
    install path (`feral install`-style) which hot-reloads the skill or
    registers the daemon / MCP server.
    """
    if not state.marketplace:
        return {"success": False, "error": "Marketplace not available"}

    kind = body.get("kind")
    item_id = body.get("id") or body.get("skill_id")

    if kind in ("skill", "daemon", "mcp") and item_id:
        try:
            install_from_registry = getattr(state.marketplace, "install_from_registry", None)
            if callable(install_from_registry):
                return await install_from_registry(kind, item_id)
        except Exception as exc:
            return {"success": False, "error": f"registry install failed: {exc}"}
        if kind == "skill":
            return await state.marketplace.install(item_id, "latest", None)
        return {
            "success": False,
            "error": f"{kind} install requires registry.feral.sh client (pending deploy)",
        }

    version = body.get("version", "latest")
    source_url = body.get("source_url")
    result = await state.marketplace.install(item_id or "", version, source_url)
    return result


@router.get("/api/marketplace/installed")
async def marketplace_installed():
    """List all marketplace-installed skills."""
    if not state.marketplace:
        return {"skills": []}
    return {"skills": state.marketplace.list_installed()}


@router.delete("/api/marketplace/uninstall/{skill_id}")
async def marketplace_uninstall(skill_id: str):
    """Uninstall a marketplace skill."""
    if not state.marketplace:
        return {"success": False, "error": "Marketplace not available"}
    return await state.marketplace.uninstall(skill_id)


@router.post("/api/marketplace/update/{skill_id}")
async def marketplace_update(skill_id: str):
    """Update a marketplace skill to latest version."""
    if not state.marketplace:
        return {"success": False, "error": "Marketplace not available"}
    return await state.marketplace.update(skill_id)


# ─────────────────────────────────────────────
# Browser Control API
# ─────────────────────────────────────────────


@router.post("/api/browser/init")
async def browser_init():
    """Initialize browser control (CDP connection)."""
    if not state.browser:
        return {"error": "Browser controller not available"}
    ok = await state.browser.initialize()
    return {"connected": ok}


@router.post("/api/browser/navigate")
async def browser_navigate(body: dict):
    if not state.browser or not state.browser.connected:
        return {"error": "Browser not connected"}
    return await state.browser.navigate(body.get("url", ""))


@router.post("/api/browser/screenshot")
async def browser_screenshot(body: dict):
    if not state.browser or not state.browser.connected:
        return {"error": "Browser not connected"}
    return await state.browser.screenshot(body.get("full_page", False))


@router.post("/api/browser/snapshot")
async def browser_snapshot():
    if not state.browser or not state.browser.connected:
        return {"error": "Browser not connected"}
    return await state.browser.snapshot()


@router.post("/api/browser/action")
async def browser_action(body: dict):
    """Execute a browser action (click, type, scroll, etc.)."""
    if not state.browser or not state.browser.connected:
        return {"error": "Browser not connected"}
    action = body.get("action", "")
    if action == "click":
        return await state.browser.click(body.get("selector", body.get("ref_or_selector", "")))
    elif action == "hover":
        return await state.browser.hover(body.get("selector", body.get("ref_or_selector", "")))
    elif action in ("type", "type_text"):
        return await state.browser.type_text(
            body.get("selector", body.get("ref_or_selector", "")),
            body.get("text", ""),
        )
    elif action == "fill_form":
        return await state.browser.fill_form(body.get("fields", {}))
    elif action == "scroll":
        return await state.browser.scroll(body.get("direction", "down"), body.get("amount", 500))
    elif action == "evaluate":
        return await state.browser.evaluate(body.get("js_code", ""))
    elif action == "select":
        return await state.browser.select(body.get("selector", ""), body.get("value", ""))
    elif action == "console_logs":
        return await state.browser.get_console_logs(body.get("limit", 50), body.get("clear", False))
    elif action == "pdf":
        return await state.browser.get_page_pdf(
            body.get("print_background", True),
            body.get("landscape", False),
        )
    elif action == "wait":
        return await state.browser.wait(body.get("ms", 1000))
    return {"error": f"Unknown action: {action}"}
