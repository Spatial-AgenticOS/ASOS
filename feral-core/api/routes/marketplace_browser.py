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


@router.post("/api/marketplace/install")
async def marketplace_install(body: dict):
    """Install a skill from the marketplace."""
    if not state.marketplace:
        return {"success": False, "error": "Marketplace not available"}
    skill_id = body.get("skill_id", "")
    version = body.get("version", "latest")
    source_url = body.get("source_url")
    result = await state.marketplace.install(skill_id, version, source_url)
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
