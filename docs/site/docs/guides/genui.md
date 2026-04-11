---
id: genui
title: GenUI Components
sidebar_position: 3
slug: /guides/genui
---

# Creating GenUI Components

FERAL's **GenUI** layer generates server-driven UI (SDUI) from tool results and provider contracts. Instead of hardcoding frontend components for every tool, the backend decides what to render and sends a declarative payload to the client.

## How It Works

1. A tool returns structured data (JSON).
2. The GenUI engine matches the data shape to a UI template.
3. An SDUI payload is sent to the client.
4. The client's `SduiRenderer` displays it — cards, charts, maps, forms, lists.

No client-side code changes required when you add a new tool.

## SDUI Payload Structure

```json
{
  "type": "sdui_payload",
  "payload": {
    "component": "MetricCard",
    "props": {
      "title": "CPU Temperature",
      "value": "72°C",
      "icon": "thermometer",
      "color": "#ef4444",
      "trend": "up"
    }
  }
}
```

### Built-in Components

| Component | Use Case |
|:----------|:---------|
| `MetricCard` | Single value with label, icon, trend indicator |
| `DataTable` | Tabular data with sortable columns |
| `BarChart` / `LineChart` | Quantitative data over categories or time |
| `MapView` | Geographic data with markers |
| `FormCard` | User input that posts back to a skill endpoint |
| `ListCard` | Ordered or unordered list of items |
| `MarkdownCard` | Rendered markdown content |
| `ImageCard` | Image with optional caption |

## Provider Surfaces

For richer experiences, a **provider** can register a full JSON contract that defines branded, multi-screen surfaces. Think of it as a mini-app inside FERAL.

### Registering a Provider

```bash
curl -X POST http://localhost:9090/api/genui/providers/register \
  -H "Content-Type: application/json" \
  -d @provider.json
```

### Provider Contract

```json
{
  "provider_id": "rideos",
  "name": "RideOS",
  "description": "Ride hailing provider",
  "base_url": "https://api.rideos.example",
  "brand": {
    "primary_color": "#111827",
    "accent_color": "#10b981",
    "logo_url": "https://rideos.example/logo.svg",
    "theme": "dark"
  },
  "ui_rules": {
    "layout_mode": "fixed",
    "brand_mode": "strict",
    "navigation_style": "bottom_tabs"
  },
  "cache_policy": {
    "mode": "static",
    "persist": true
  },
  "endpoints": [
    { "id": "quote", "method": "POST", "path": "/quote" },
    { "id": "book",  "method": "POST", "path": "/book" }
  ],
  "surfaces": [
    {
      "id": "home",
      "title": "Book a Ride",
      "entry": true,
      "template": {
        "type": "VStack",
        "spacing": 16,
        "children": [
          { "type": "Text", "value": "$headline", "style": "headline" },
          { "type": "MapView", "center": "$user_location", "markers": "$nearby_drivers" },
          { "type": "Button", "label": "$cta_label", "action_id": "request_ride" }
        ]
      }
    },
    {
      "id": "trip_status",
      "title": "Your Trip",
      "template": {
        "type": "VStack",
        "children": [
          { "type": "MapView", "route": "$route_polyline" },
          { "type": "MetricCard", "title": "ETA", "value": "$eta_minutes" },
          { "type": "Button", "label": "Cancel Ride", "action_id": "cancel_ride", "style": "destructive" }
        ]
      }
    }
  ]
}
```

### Surface Lifecycle

1. **Register** — provider posts its contract via the API.
2. **Compile** — FERAL compiles each named surface into SDUI JSON and caches it locally in `~/.feral/genui_surfaces/`.
3. **Serve** — subsequent opens reuse the cached layout shell; only runtime data (prefixed with `$`) is hydrated.
4. **Update** — if the provider pushes a new contract version, the cache is invalidated and recompiled.

```bash
# Compile surfaces
curl -X POST http://localhost:9090/api/genui/providers/rideos/surfaces/compile

# Render with runtime data
curl -X POST http://localhost:9090/api/genui/providers/rideos/surfaces/render \
  -d '{"surface_id": "home", "data": {"headline": "Where to?", "cta_label": "Request Ride"}}'
```

### Contract Fields

| Field | Required | Description |
|:------|:---------|:------------|
| `provider_id` | yes | Unique ID |
| `name` | yes | Display name |
| `brand` | no | Colors, logo, theme |
| `ui_rules` | no | Layout mode (`fixed` or `adaptive`), brand strictness, navigation style |
| `cache_policy` | no | `static` (compile once) or `dynamic` (regenerate per session) |
| `endpoints[]` | yes | Backend endpoints the surface can call |
| `surfaces[]` | yes | Named UI screens with declarative templates |

### Template Primitives

| Type | Description |
|:-----|:------------|
| `VStack` | Vertical layout container |
| `HStack` | Horizontal layout container |
| `Text` | Text label with style variants (headline, body, caption) |
| `Button` | Tappable action with an `action_id` |
| `MapView` | Map with center, markers, routes |
| `MetricCard` | Single metric display |
| `Image` | Image with URL and optional alt text |
| `Input` | Text input field |
| `Select` | Dropdown or picker |

## Client-Side Rendering

The web UI's `SduiRenderer` component (`feral-client/src/components/SduiRenderer.jsx`) recursively renders SDUI payloads. When adding a new component type:

1. Define the component in the renderer's component map.
2. Handle the `props` passed from the SDUI payload.
3. Wire up any `action_id` handlers to post back to the Brain.

The renderer is intentionally minimal — you can replace it with any SDUI rendering framework.

## API Reference

| Endpoint | Method | Description |
|:---------|:-------|:------------|
| `/api/genui/providers/register` | POST | Register a provider contract |
| `/api/genui/providers` | GET | List registered providers |
| `/api/genui/providers/{id}/surfaces` | GET | List surfaces + cache status |
| `/api/genui/providers/{id}/surfaces/{sid}` | GET | Get one surface contract |
| `/api/genui/providers/{id}/surfaces/compile` | POST | Compile and cache surfaces |
| `/api/genui/providers/{id}/surfaces/render` | POST | Render runtime data into cached surface |
