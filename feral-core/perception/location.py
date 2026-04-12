"""
FERAL Location & Geofence Engine
====================================
GPS tracking and geofence management with enter/exit detection.
Uses pure math for haversine distance and SQLite for persistence.
"""

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

from config.loader import feral_data_home

logger = logging.getLogger("feral.perception.location")

EARTH_RADIUS_M = 6_371_000


@dataclass
class GeoPoint:
    lat: float
    lon: float
    name: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class Geofence:
    center: GeoPoint
    radius_m: float
    name: str
    on_enter: str = ""
    on_exit: str = ""


class LocationEngine:
    """GPS tracking with persistent geofences and enter/exit detection."""

    def __init__(self):
        self._db_path = feral_data_home() / "location.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_db()

        self.current_location: Optional[GeoPoint] = None
        self._inside_fences: set[str] = set()
        self._callbacks: list[Callable[..., Awaitable[None]]] = []

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS geofences (
                name        TEXT PRIMARY KEY,
                lat         REAL NOT NULL,
                lon         REAL NOT NULL,
                radius_m    REAL NOT NULL,
                on_enter    TEXT DEFAULT '',
                on_exit     TEXT DEFAULT '',
                created_at  REAL DEFAULT (strftime('%%s', 'now'))
            )
        """)
        self._conn.commit()
        for row in self._conn.execute("SELECT name FROM geofences"):
            pass  # schema validated

    def _load_fence(self, row: sqlite3.Row) -> Geofence:
        return Geofence(
            center=GeoPoint(lat=row["lat"], lon=row["lon"], name=row["name"]),
            radius_m=row["radius_m"],
            name=row["name"],
            on_enter=row["on_enter"] or "",
            on_exit=row["on_exit"] or "",
        )

    def add_geofence(self, name: str, lat: float, lon: float, radius_m: float,
                     on_enter: str = "", on_exit: str = "") -> Geofence:
        self._conn.execute(
            """INSERT OR REPLACE INTO geofences (name, lat, lon, radius_m, on_enter, on_exit)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, lat, lon, radius_m, on_enter, on_exit),
        )
        self._conn.commit()
        fence = Geofence(
            center=GeoPoint(lat=lat, lon=lon, name=name),
            radius_m=radius_m,
            name=name,
            on_enter=on_enter,
            on_exit=on_exit,
        )
        logger.info("Geofence added: %s (%.6f, %.6f) r=%dm", name, lat, lon, radius_m)
        return fence

    def remove_geofence(self, name: str) -> bool:
        cur = self._conn.execute("DELETE FROM geofences WHERE name = ?", (name,))
        self._conn.commit()
        self._inside_fences.discard(name)
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Geofence removed: %s", name)
        return deleted

    def list_geofences(self) -> list[Geofence]:
        rows = self._conn.execute("SELECT * FROM geofences ORDER BY name").fetchall()
        return [self._load_fence(row) for row in rows]

    async def update_location(self, lat: float, lon: float,
                              source: str = "phone") -> list[dict[str, Any]]:
        """Update current location, check geofences, fire callbacks.

        Returns a list of triggered fence events.
        """
        point = GeoPoint(lat=lat, lon=lon, name=source)
        self.current_location = point
        logger.debug("Location updated: (%.6f, %.6f) source=%s", lat, lon, source)

        triggered = self.check_fences(point)

        for event in triggered:
            for cb in self._callbacks:
                try:
                    await cb(event)
                except Exception as e:
                    logger.warning("Geofence callback error: %s", e)

        return triggered

    def check_fences(self, point: GeoPoint) -> list[dict[str, Any]]:
        """Check all fences against a point. Returns list of enter/exit events."""
        fences = self.list_geofences()
        triggered: list[dict[str, Any]] = []

        for fence in fences:
            dist = self._haversine(point, fence.center)
            inside = dist <= fence.radius_m
            was_inside = fence.name in self._inside_fences

            if inside and not was_inside:
                self._inside_fences.add(fence.name)
                triggered.append({
                    "fence": fence.name,
                    "event": "enter",
                    "action": fence.on_enter,
                    "distance_m": round(dist, 1),
                    "timestamp": time.time(),
                })
                logger.info("Entered geofence: %s (dist=%.0fm)", fence.name, dist)

            elif not inside and was_inside:
                self._inside_fences.discard(fence.name)
                triggered.append({
                    "fence": fence.name,
                    "event": "exit",
                    "action": fence.on_exit,
                    "distance_m": round(dist, 1),
                    "timestamp": time.time(),
                })
                logger.info("Exited geofence: %s (dist=%.0fm)", fence.name, dist)

        return triggered

    def distance_to(self, name: str) -> Optional[float]:
        """Distance in meters from current location to a named fence center."""
        if not self.current_location:
            return None
        row = self._conn.execute(
            "SELECT lat, lon FROM geofences WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return None
        target = GeoPoint(lat=row["lat"], lon=row["lon"])
        return round(self._haversine(self.current_location, target), 1)

    def on_trigger(self, callback: Callable[..., Awaitable[None]]):
        """Register an async callback for geofence enter/exit events."""
        self._callbacks.append(callback)

    @staticmethod
    def _haversine(p1: GeoPoint, p2: GeoPoint) -> float:
        """Great-circle distance between two points in meters."""
        lat1, lon1 = math.radians(p1.lat), math.radians(p1.lon)
        lat2, lon2 = math.radians(p2.lat), math.radians(p2.lon)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return EARTH_RADIUS_M * c

    def close(self):
        self._conn.close()
