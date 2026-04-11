"""FERAL Weather skill — OpenWeatherMap + wttr.in fallback; lat/lon for GenUI MapView."""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional

import httpx

from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("feral.skills.weather")


def _loc(args: Dict[str, Any]) -> str:
    return (args.get("q") or args.get("location") or args.get("city") or "").strip()


def _wttr_desc(desc: Any) -> str:
    if not desc:
        return ""
    x = desc[0] if isinstance(desc, list) else desc
    return x.get("value", x) if isinstance(x, dict) else str(x)


def _parse_lat_lon(nearest: dict) -> tuple[Optional[float], Optional[float]]:
    try:
        la, lo = nearest.get("latitude"), nearest.get("longitude")
        return (float(la) if la is not None else None, float(lo) if lo is not None else None)
    except (TypeError, ValueError):
        return None, None


async def _wttr_j1(client: httpx.AsyncClient, q: str) -> dict:
    r = await client.get(f"https://wttr.in/{q.replace(' ', '+')}?format=j1", follow_redirects=True)
    r.raise_for_status()
    return r.json()


async def _owm_current(c: httpx.AsyncClient, q: str, units: str, key: str) -> Dict[str, Any]:
    r = await c.get("https://api.openweathermap.org/data/2.5/weather", params={"q": q, "units": units, "appid": key})
    r.raise_for_status()
    j = r.json()
    coord = j.get("coord") or {}
    w0 = (j.get("weather") or [{}])[0]
    m, w = j.get("main") or {}, j.get("wind") or {}
    return {
        "location": j.get("name", q),
        "country": (j.get("sys") or {}).get("country"),
        "lat": coord.get("lat"),
        "lon": coord.get("lon"),
        "temperature": m.get("temp"),
        "feels_like": m.get("feels_like"),
        "humidity": m.get("humidity"),
        "conditions": w0.get("description", ""),
        "wind_speed": w.get("speed"),
        "units": units,
        "provider": "openweathermap",
    }


async def _owm_forecast(c: httpx.AsyncClient, q: str, units: str, key: str) -> Dict[str, Any]:
    r = await c.get("https://api.openweathermap.org/data/2.5/forecast", params={"q": q, "units": units, "appid": key})
    r.raise_for_status()
    j = r.json()
    city = j.get("city") or {}
    coord, cname = city.get("coord") or {}, city.get("name", q)
    by_day: Dict[str, List[dict]] = defaultdict(list)
    for item in j.get("list") or []:
        dk = (item.get("dt_txt") or "").split(" ")[0]
        if not dk:
            continue
        m, w0 = item.get("main") or {}, (item.get("weather") or [{}])[0]
        by_day[dk].append({"temp": m.get("temp"), "conditions": w0.get("description", "")})
    days: List[Dict[str, Any]] = []
    for dk in sorted(by_day.keys())[:3]:
        sl = by_day[dk]
        temps = [x["temp"] for x in sl if x.get("temp") is not None]
        cond = max(sl, key=lambda x: len(x.get("conditions") or ""), default={}).get("conditions", "")
        days.append({"date": dk, "temp_high": max(temps) if temps else None, "temp_low": min(temps) if temps else None, "conditions": cond})
    return {"location": cname, "lat": coord.get("lat"), "lon": coord.get("lon"), "days": days, "units": units, "provider": "openweathermap"}


def _from_wttr_current(j: dict, q: str) -> Dict[str, Any]:
    cur, na = (j.get("current_condition") or [{}])[0], (j.get("nearest_area") or [{}])[0]
    lat, lon = _parse_lat_lon(na)
    return {
        "location": (na.get("areaName") or [q])[0],
        "country": (na.get("country") or [""])[0],
        "lat": lat,
        "lon": lon,
        "temperature": float(cur.get("temp_C", 0) or 0),
        "feels_like": float(cur.get("FeelsLikeC", cur.get("temp_C", 0)) or 0),
        "humidity": int(cur.get("humidity", 0) or 0),
        "conditions": _wttr_desc(cur.get("weatherDesc")),
        "wind_speed": float(cur.get("windspeedKmph", 0) or 0) / 3.6,
        "units": "metric",
        "provider": "wttr.in",
    }


def _from_wttr_forecast(j: dict, q: str) -> Dict[str, Any]:
    na = (j.get("nearest_area") or [{}])[0]
    lat, lon = _parse_lat_lon(na)
    days: List[Dict[str, Any]] = []
    for d in (j.get("weather") or [])[:3]:
        h0 = (d.get("hourly") or [{}])[0]
        wd = (h0.get("weatherDesc") or [{}])[0]
        days.append({
            "date": d.get("date", ""),
            "temp_high": float(d.get("maxtempC", 0) or 0),
            "temp_low": float(d.get("mintempC", 0) or 0),
            "conditions": wd.get("value", "") if isinstance(wd, dict) else "",
        })
    return {"location": (na.get("areaName") or [q])[0], "lat": lat, "lon": lon, "days": days, "units": "metric", "provider": "wttr.in"}


@register_skill
class WeatherSkill(BaseSkill):
    name = "Weather"
    description = "Current conditions and short forecast with coordinates for maps."
    safety_level = "SAFE"

    def __init__(self) -> None:
        super().__init__(skill_id="weather_current")

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        q = _loc(args)
        if not q:
            return {"success": False, "status_code": 400, "data": None, "error": "Missing location. Pass 'q' (e.g. city name)."}
        units = (args.get("units") or "metric").strip() or "metric"
        key: Optional[str] = self.get_api_key(vault, fallback_env="OPENWEATHER_API_KEY") or os.getenv("OPENWEATHER_API_KEY")

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                if endpoint_id == "current":
                    data = await _owm_current(client, q, units, key) if key else _from_wttr_current(await _wttr_j1(client, q), q)
                    return {"success": True, "status_code": 200, "data": data, "error": None}
                if endpoint_id == "forecast":
                    data = await _owm_forecast(client, q, units, key) if key else _from_wttr_forecast(await _wttr_j1(client, q), q)
                    return {"success": True, "status_code": 200, "data": data, "error": None}
                return {"success": False, "status_code": 404, "data": None, "error": f"Unknown endpoint: {endpoint_id}"}
            except httpx.HTTPStatusError as e:
                if key and endpoint_id in ("current", "forecast"):
                    try:
                        j = await _wttr_j1(client, q)
                        data = _from_wttr_current(j, q) if endpoint_id == "current" else _from_wttr_forecast(j, q)
                        data["fallback_from"] = "openweathermap_error"
                        return {"success": True, "status_code": 200, "data": data, "error": None}
                    except Exception as fe:
                        logger.debug("wttr fallback failed: %s", fe)
                err = e.response.text[:300] if e.response else str(e)
                return {"success": False, "status_code": e.response.status_code if e.response else 0, "data": None, "error": err}
            except httpx.RequestError as e:
                return {"success": False, "status_code": 0, "data": None, "error": str(e)}
