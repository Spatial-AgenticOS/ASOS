"""GenUI service provider endpoints and theming API."""

from fastapi import APIRouter

from api.state import state

router = APIRouter()

_DEFAULT_THEME = {
    "name": "feral-dark",
    "colors": {
        "primary": "#06b6d4",
        "secondary": "#8b5cf6",
        "accent": "#06b6d4",
        "background": "#0a0a0a",
        "surface": "#1a1a2e",
        "border": "rgba(255,255,255,0.1)",
        "text": "#f0f0f0",
        "text_muted": "rgba(255,255,255,0.5)",
        "success": "#10b981",
        "warning": "#f59e0b",
        "error": "#ef4444",
    },
    "typography": {
        "font_family": "Inter, system-ui, sans-serif",
        "heading_weight": "700",
        "body_size": "14px",
    },
    "radius": "12px",
    "spacing_unit": 4,
}

_THEMES: dict = {"feral-dark": _DEFAULT_THEME}
_ACTIVE_THEME = "feral-dark"


@router.post("/api/genui/providers/register")
async def register_genui_provider(body: dict):
    """Register an external service provider for GenUI."""
    if not state.service_providers:
        return {"error": "Service provider registry not initialized"}
    provider = state.service_providers.register(body)
    if state.genui_engine:
        state.genui_engine.register_provider(provider)
    return {"ok": True, "provider_id": provider.provider_id, "components": list(provider.components.keys())}


@router.get("/api/genui/providers")
async def list_genui_providers():
    """List registered service providers."""
    if not state.service_providers:
        return {"providers": []}
    return {"providers": state.service_providers.list_providers()}


@router.get("/api/genui/providers/{provider_id}/surfaces")
async def list_genui_provider_surfaces(provider_id: str):
    """List provider-defined GenUI surfaces and cache status."""
    if not state.service_providers:
        return {"error": "Service provider registry not initialized"}
    provider = state.service_providers.get(provider_id)
    if not provider:
        return {"error": "Provider not found"}

    surfaces = provider.list_surfaces()
    if state.genui_engine:
        surfaces = state.genui_engine.list_provider_surfaces(provider_id)

    return {
        "provider_id": provider_id,
        "brand": provider.brand,
        "ui_rules": provider.ui_rules,
        "cache_policy": provider.cache_policy,
        "surfaces": surfaces,
    }


@router.get("/api/genui/providers/{provider_id}/surfaces/{surface_id}")
async def get_genui_provider_surface(provider_id: str, surface_id: str):
    """Get one provider surface contract plus cached layout, if compiled."""
    if not state.service_providers:
        return {"error": "Service provider registry not initialized"}
    provider = state.service_providers.get(provider_id)
    if not provider:
        return {"error": "Provider not found"}

    surface = provider.get_surface(surface_id)
    if not surface:
        return {"error": "Surface not found"}

    cached = state.genui_engine.get_cached_surface(provider_id, surface_id) if state.genui_engine else None
    return {
        "provider_id": provider_id,
        "surface_id": surface_id,
        "surface": surface,
        "cached": cached,
    }


@router.post("/api/genui/providers/{provider_id}/surfaces/compile")
async def compile_genui_provider_surface(provider_id: str, body: dict):
    """Compile a provider surface once and persist the layout."""
    if not state.genui_engine:
        return {"error": "GenUI engine not initialized"}

    surface_id = body.get("surface_id") or body.get("id", "")
    if not surface_id:
        return {"error": "surface_id is required"}

    return await state.genui_engine.compile_provider_surface(
        provider_id=provider_id,
        surface_id=surface_id,
        force=bool(body.get("force")),
    )


@router.post("/api/genui/providers/{provider_id}/surfaces/render")
async def render_genui_provider_surface(provider_id: str, body: dict):
    """Render a provider surface from the cached fixed layout."""
    if not state.genui_engine:
        return {"error": "GenUI engine not initialized"}

    surface_id = body.get("surface_id") or body.get("id", "")
    if not surface_id:
        return {"error": "surface_id is required"}

    return await state.genui_engine.render_provider_surface(
        provider_id=provider_id,
        surface_id=surface_id,
        data=body.get("data") or {},
        force_compile=bool(body.get("force")),
    )


# ── Theming API ──

@router.get("/api/genui/themes")
async def list_themes():
    """List available SDUI themes."""
    return {"themes": list(_THEMES.keys()), "active": _ACTIVE_THEME}


@router.get("/api/genui/themes/{theme_id}")
async def get_theme(theme_id: str):
    """Get a theme by ID."""
    theme = _THEMES.get(theme_id)
    if not theme:
        return {"error": f"Theme '{theme_id}' not found"}
    return theme


@router.post("/api/genui/themes")
async def create_theme(body: dict):
    """Create or update a custom SDUI theme."""
    global _ACTIVE_THEME
    name = body.get("name", "").strip()
    if not name:
        return {"error": "Theme name is required"}
    _THEMES[name] = {**_DEFAULT_THEME, **body, "name": name}
    if body.get("activate"):
        _ACTIVE_THEME = name
    return {"ok": True, "theme": _THEMES[name]}


@router.post("/api/genui/themes/activate")
async def activate_theme(body: dict):
    """Set the active SDUI theme."""
    global _ACTIVE_THEME
    name = body.get("name", "").strip()
    if name not in _THEMES:
        return {"error": f"Theme '{name}' not found"}
    _ACTIVE_THEME = name
    return {"ok": True, "active": _ACTIVE_THEME}


@router.get("/api/genui/components")
async def list_genui_components():
    """List all available SDUI component types with descriptions."""
    return {"components": [
        {"type": "VStack", "description": "Vertical stack layout"},
        {"type": "HStack", "description": "Horizontal stack layout"},
        {"type": "Card", "description": "Elevated card container"},
        {"type": "Text", "description": "Text element with style variants (headline, subtitle, body, caption)"},
        {"type": "Icon", "description": "Lucide icon by name"},
        {"type": "Badge", "description": "Colored badge/label"},
        {"type": "Button", "description": "Interactive button with action_id"},
        {"type": "MetricCard", "description": "Numeric metric with icon, value, label, unit"},
        {"type": "ProgressBar", "description": "Progress indicator with value 0-1"},
        {"type": "Image", "description": "Image from URL"},
        {"type": "Grid", "description": "CSS grid layout with configurable columns"},
        {"type": "ScrollView", "description": "Scrollable container"},
        {"type": "Chart", "description": "Line or bar chart from data array"},
        {"type": "MapView", "description": "Interactive map with markers (Leaflet)"},
        {"type": "GraphView", "description": "Knowledge graph visualization (nodes + links)"},
        {"type": "AudioPlayer", "description": "Audio player with play/pause and progress"},
        {"type": "VideoPlayer", "description": "Video player with controls"},
        {"type": "MediaPlayer", "description": "Unified audio/video player"},
        {"type": "FormView", "description": "Interactive form with inputs, selects, textareas"},
        {"type": "Toggle", "description": "Toggle/switch control"},
        {"type": "Accordion", "description": "Expandable sections"},
        {"type": "Table", "description": "Data table with headers and rows"},
        {"type": "CodeBlock", "description": "Syntax-highlighted code block"},
        {"type": "Markdown", "description": "Rendered markdown content"},
        {"type": "WebView", "description": "Embedded iframe"},
        {"type": "Divider", "description": "Horizontal divider line"},
        {"type": "Skeleton", "description": "Loading placeholder"},
        {"type": "Spacer", "description": "Vertical spacer"},
    ]}
