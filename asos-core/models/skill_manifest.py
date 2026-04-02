"""
THEORA Skill Manifest — The Skill Definition Format
=====================================================
This is what developers and companies submit to make their
service available in THEORA. Compatible with MCP, extended
with GenUI hints, flows, and cron/trigger support.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import uuid4


class BrandProfile(BaseModel):
    """Visual identity for GenUI rendering."""
    name: str
    primary_color: str = "#007AFF"
    secondary_color: str = "#5856D6"
    logo_url: str = ""
    icon_set: Literal["sf_symbols", "material", "custom"] = "sf_symbols"


class AuthConfig(BaseModel):
    """How the skill authenticates with its backend."""
    type: Literal["none", "api_key", "oauth2", "bearer"]
    api_key_header: Optional[str] = None  # e.g. "X-API-Key"
    authorize_url: Optional[str] = None
    token_url: Optional[str] = None
    scopes: list[str] = []


class EndpointParam(BaseModel):
    """A parameter for a skill endpoint."""
    name: str
    type: Literal["string", "number", "boolean", "array", "object"] = "string"
    items: Optional[dict] = None
    required: bool = True
    description: str = ""
    default: Optional[str] = None
    enum: list[str] = []  # Valid values


class SkillEndpoint(BaseModel):
    """A single API endpoint the skill exposes."""
    id: str
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "GET"
    url: str
    description: str  # Natural language — this is what the LLM reads
    params: list[EndpointParam] = []
    returns_description: str = ""  # What the response contains
    ui_hint: Optional[str] = None  # "grid_cards", "detail_card", "map", "list", "metric"


class FlowStep(BaseModel):
    """One step in a multi-step flow."""
    endpoint_id: str
    condition: Optional[str] = None  # e.g. "result.rain_probability > 0.5"
    then_endpoint_id: Optional[str] = None


class SkillFlow(BaseModel):
    """A multi-step orchestration (e.g., search → select → order → confirm)."""
    id: str
    description: str
    steps: list[FlowStep] = []


class CronDefinition(BaseModel):
    """A scheduled background job."""
    id: str
    schedule: str  # cron format: "0 8 * * 1-5" = weekdays at 8am
    flow_id: Optional[str] = None  # Execute a flow on schedule
    endpoint_id: Optional[str] = None  # Or execute a single endpoint


class TriggerDefinition(BaseModel):
    """An event-driven reaction."""
    id: str
    condition: str  # e.g. "biometric.heart_rate_bpm > 150"
    action_flow_id: Optional[str] = None
    action_endpoint_id: Optional[str] = None
    cooldown_seconds: int = 300  # Don't re-trigger for 5 min


class SkillManifest(BaseModel):
    """
    The complete skill definition.
    This is what developers submit to register a skill with THEORA.
    MCP-compatible at the tool level, extended with GenUI + flows.
    """
    skill_id: str = Field(default_factory=lambda: str(uuid4()))
    version: str = "1.0.0"
    author: str = ""
    
    # Brand & Discovery
    brand: BrandProfile
    description: str  # Natural language description for the LLM
    trigger_phrases: list[str] = []  # Hint phrases that activate this skill
    categories: list[str] = []  # ["food", "transport", "productivity", ...]
    
    # Auth
    auth: AuthConfig = AuthConfig(type="none")
    
    # Endpoints (individual capabilities)
    endpoints: list[SkillEndpoint] = []
    
    # Flows (multi-step orchestrations)
    flows: list[SkillFlow] = []
    
    # Background jobs
    crons: list[CronDefinition] = []
    
    # Event triggers
    triggers: list[TriggerDefinition] = []
    
    # Permissions
    permissions: list[str] = []  # ["location", "contacts", "camera", "messaging"]
    
    # Hardware requirements (for hardware skills)
    requires_daemon: bool = False
    daemon_node_type: Optional[str] = None  # "desktop", "rpi", "robot"
    
    # Rate limits
    max_calls_per_hour: int = 1000


# ─────────────────────────────────────────────
# Example: Weather Skill
# ─────────────────────────────────────────────

WEATHER_SKILL = SkillManifest(
    skill_id="weather_current",
    version="1.0.0",
    author="theora-core",
    brand=BrandProfile(
        name="Weather",
        primary_color="#4A90D9",
        logo_url="",
        icon_set="sf_symbols",
    ),
    description="Get current weather conditions and forecasts for any location.",
    trigger_phrases=[
        "what's the weather",
        "is it going to rain",
        "temperature outside",
        "weather forecast",
        "do I need an umbrella",
        "how hot is it",
    ],
    categories=["weather", "utility"],
    auth=AuthConfig(type="api_key", api_key_header="X-API-Key"),
    endpoints=[
        SkillEndpoint(
            id="current_weather",
            method="GET",
            url="https://api.openweathermap.org/data/2.5/weather",
            description="Get current weather for a location. Returns temperature, conditions, humidity, wind.",
            params=[
                EndpointParam(name="lat", type="number", description="Latitude"),
                EndpointParam(name="lon", type="number", description="Longitude"),
                EndpointParam(name="units", type="string", default="imperial", description="Temperature units"),
            ],
            returns_description="temp, feels_like, humidity, weather_description, wind_speed, icon_code",
            ui_hint="metric",
        ),
        SkillEndpoint(
            id="forecast_5day",
            method="GET",
            url="https://api.openweathermap.org/data/2.5/forecast",
            description="Get 5-day forecast. Returns temperature and conditions for each day.",
            params=[
                EndpointParam(name="lat", type="number", description="Latitude"),
                EndpointParam(name="lon", type="number", description="Longitude"),
            ],
            returns_description="Array of daily forecasts with temp_high, temp_low, conditions",
            ui_hint="list",
        ),
    ],
)
