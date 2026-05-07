"""
Node sub-device truth store.

A "sub-device" is anything an HUP node owns that is not the node itself —
the Theora glasses paired over BLE through the iPhone companion, an Apple
Health pipeline behind the same phone, a cloud-synced Whoop account
attached to a paired phone, etc.

The brain is the single source of truth for sub-device status because:

* Multiple consumers (web dashboard, native iOS UI, future MCP clients,
  the orchestrator's prompt context) all need the same view.
* Liveness must be enforced uniformly. A row that hasn't received a
  heartbeat inside its provenance-specific window auto-derates so no
  surface can show "Active" indefinitely.
* It must survive brain restart: the iOS app re-emits on next pair, but
  between restarts we keep the prior view available rather than blanking
  the dashboard.

The store persists to ``memory.db`` (table ``node_subdevices``) keyed by
``(node_id, capability)``. Every mutation fires an ``on_change`` callback
so ``BrainState`` can broadcast ``subdevice_update`` to every connected
session WebSocket.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Callable, Optional

logger = logging.getLogger("feral.subdevices")


# Liveness windows (seconds) keyed by provenance. A sub-device is
# considered "live" only if ``now - last_seen <= window``. After the
# window, the persisted ``status`` is preserved but the runtime ``live``
# flag is False and downstream UI must downgrade the indicator.
LIVENESS_WINDOWS: dict[str, float] = {
    "ble": 30.0,
    "cloud": 300.0,
    "host": 60.0,
    # Used by tests so they can verify the live → stale transition
    # without sleeping for 30 seconds. Production code never emits
    # this provenance.
    "synthetic": 5.0,
}
DEFAULT_LIVENESS_WINDOW = 30.0


# Allowed provenance values. The store rejects anything else so a typo in
# a HUP frame can't silently produce a row that never derates.
ALLOWED_PROVENANCES = frozenset(LIVENESS_WINDOWS.keys())


def liveness_window(provenance: str) -> float:
    return LIVENESS_WINDOWS.get(provenance, DEFAULT_LIVENESS_WINDOW)


# Type alias for the change-callback signature. Receivers must not block;
# the store schedules them on the main loop via ``BrainState.broadcast_event``.
OnChange = Callable[[str, dict], None]


class NodeSubdeviceStore:
    """SQLite-backed truth store for HUP node sub-devices.

    Public contract:

    * ``upsert(...)`` writes a row, refreshes ``last_seen`` to *now*, and
      fires ``on_change("subdevice_update", record)``.
    * ``forget(node_id, capability=None)`` deletes one row or every row
      for the node (used on ``node_bye``) and fires
      ``on_change("subdevice_remove", {...})`` per row removed.
    * ``sweep_stale(now=None)`` walks every row, computes the live flag
      for each, and fires ``on_change("subdevice_update", record)`` only
      when a row transitions live ↔ stale relative to the prior sweep.

    Threading: every method opens its own short-lived SQLite connection.
    The in-memory ``_live_state`` cache is mutated only inside method
    bodies; callers from coroutines should keep mutations on a single
    event-loop task, but read methods are safe to call concurrently.
    """

    def __init__(self, db_path: str, *, on_change: Optional[OnChange] = None):
        self.db_path = db_path
        self._on_change = on_change
        # Tracks the last-known live flag per (node_id, capability) so
        # ``sweep_stale`` only emits deltas, not every row every tick.
        self._live_state: dict[tuple[str, str], bool] = {}
        self._init_db()
        self._hydrate_live_state()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS node_subdevices (
                    node_id     TEXT NOT NULL,
                    capability  TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    attrs       TEXT NOT NULL DEFAULT '{}',
                    provenance  TEXT NOT NULL DEFAULT 'ble',
                    first_seen  REAL NOT NULL,
                    last_seen   REAL NOT NULL,
                    PRIMARY KEY (node_id, capability)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_subdevices_node ON node_subdevices(node_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_subdevices_lastseen ON node_subdevices(last_seen DESC)"
            )
            conn.commit()
        finally:
            conn.close()

    def _hydrate_live_state(self) -> None:
        """Seed ``_live_state`` from disk so the first ``sweep_stale``
        emits transitions only for rows that actually changed since the
        previous brain run.
        """
        now = time.time()
        for record in self._fetch_all():
            key = (record["node_id"], record["capability"])
            self._live_state[key] = self._is_live(record, now=now)

    def set_on_change(self, on_change: Optional[OnChange]) -> None:
        self._on_change = on_change

    # ------------------------------------------------------------------
    # Public mutators
    # ------------------------------------------------------------------

    def upsert(
        self,
        *,
        node_id: str,
        capability: str,
        status: str,
        attrs: Optional[dict] = None,
        provenance: str = "ble",
        observed_at: Optional[float] = None,
    ) -> dict:
        """Upsert a sub-device record and emit ``subdevice_update``.

        ``status`` is opaque domain text (``"ready"``, ``"failed"``,
        ``"connecting"``, ``"online"``, ``"stale"``, etc.). The runtime
        ``live`` flag in the emitted record is computed from
        ``observed_at`` against the provenance window — callers should
        not pre-compute it.
        """
        if not node_id or not capability:
            raise ValueError("node_id and capability are required")
        if not status:
            raise ValueError("status is required")
        if provenance not in ALLOWED_PROVENANCES:
            raise ValueError(
                f"unknown provenance {provenance!r}; expected one of "
                f"{sorted(ALLOWED_PROVENANCES)}"
            )
        ts = float(observed_at) if observed_at is not None else time.time()
        attrs_json = json.dumps(attrs or {}, sort_keys=True)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT first_seen FROM node_subdevices WHERE node_id = ? AND capability = ?",
                (node_id, capability),
            ).fetchone()
            first_seen = float(existing["first_seen"]) if existing is not None else ts
            conn.execute(
                """
                INSERT INTO node_subdevices
                  (node_id, capability, status, attrs, provenance, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id, capability) DO UPDATE SET
                  status     = excluded.status,
                  attrs      = excluded.attrs,
                  provenance = excluded.provenance,
                  last_seen  = excluded.last_seen
                """,
                (node_id, capability, status, attrs_json, provenance, first_seen, ts),
            )
            conn.commit()
        finally:
            conn.close()

        record = {
            "node_id": node_id,
            "capability": capability,
            "status": status,
            "attrs": attrs or {},
            "provenance": provenance,
            "first_seen": first_seen,
            "last_seen": ts,
            "live": True,  # we just observed it; it is by definition live now
            "liveness_window_s": liveness_window(provenance),
        }
        # Update sweep tracker so sweep_stale doesn't re-emit live=True.
        self._live_state[(node_id, capability)] = True
        self._emit("subdevice_update", record)
        return record

    def forget(self, node_id: str, capability: Optional[str] = None) -> int:
        """Remove sub-device rows. ``capability=None`` removes every row
        for the node.

        **Not** called from the brain's ``node_bye`` / WebSocket
        disconnect paths — that's a deliberate design choice: the
        rows must survive brain restart and operator-driven reboots
        of the iOS app so the dashboard still has *something* to
        render between restarts. Liveness is enforced by
        :meth:`sweep_stale` which derates each row's ``live`` flag
        once its provenance heartbeat window expires; the persisted
        ``status`` text is preserved across the derate so operators
        still see the last-known state.

        Use this method only for explicit operator action (``DELETE``
        REST endpoint, future Devices-tab "Forget device" button) or
        in tests that need to scrub the table.

        Returns the number of rows removed. Emits one
        ``subdevice_remove`` event per removed row.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            if capability is None:
                rows = conn.execute(
                    "SELECT node_id, capability FROM node_subdevices WHERE node_id = ?",
                    (node_id,),
                ).fetchall()
                conn.execute(
                    "DELETE FROM node_subdevices WHERE node_id = ?", (node_id,)
                )
            else:
                rows = conn.execute(
                    "SELECT node_id, capability FROM node_subdevices "
                    "WHERE node_id = ? AND capability = ?",
                    (node_id, capability),
                ).fetchall()
                conn.execute(
                    "DELETE FROM node_subdevices WHERE node_id = ? AND capability = ?",
                    (node_id, capability),
                )
            conn.commit()
        finally:
            conn.close()

        for row in rows:
            key = (row["node_id"], row["capability"])
            self._live_state.pop(key, None)
            self._emit(
                "subdevice_remove",
                {"node_id": row["node_id"], "capability": row["capability"]},
            )
        return len(rows)

    # ------------------------------------------------------------------
    # Public readers
    # ------------------------------------------------------------------

    def get(self, node_id: str, capability: str, *, now: Optional[float] = None) -> Optional[dict]:
        ts = float(now) if now is not None else time.time()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT node_id, capability, status, attrs, provenance, first_seen, last_seen "
                "FROM node_subdevices WHERE node_id = ? AND capability = ?",
                (node_id, capability),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return self._row_to_record(row, now=ts)

    def list_for_node(self, node_id: str, *, now: Optional[float] = None) -> list[dict]:
        ts = float(now) if now is not None else time.time()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT node_id, capability, status, attrs, provenance, first_seen, last_seen "
                "FROM node_subdevices WHERE node_id = ? ORDER BY last_seen DESC",
                (node_id,),
            ).fetchall()
        finally:
            conn.close()
        return [self._row_to_record(r, now=ts) for r in rows]

    def list_all(self, *, now: Optional[float] = None) -> list[dict]:
        ts = float(now) if now is not None else time.time()
        return [self._row_to_record(r, now=ts) for r in self._fetch_all()]

    # ------------------------------------------------------------------
    # Liveness sweep
    # ------------------------------------------------------------------

    def sweep_stale(self, *, now: Optional[float] = None) -> list[dict]:
        """Walk every row; emit ``subdevice_update`` for any that
        transitioned live ↔ stale relative to the previous sweep.

        Returns the list of emitted records (post-transition view).
        """
        ts = float(now) if now is not None else time.time()
        emitted: list[dict] = []
        for row in self._fetch_all():
            record = self._row_to_record(row, now=ts)
            key = (record["node_id"], record["capability"])
            prev_live = self._live_state.get(key)
            if prev_live is None or prev_live != record["live"]:
                self._live_state[key] = record["live"]
                self._emit("subdevice_update", record)
                emitted.append(record)
        return emitted

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch_all(self) -> list[sqlite3.Row]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            return list(
                conn.execute(
                    "SELECT node_id, capability, status, attrs, provenance, first_seen, last_seen "
                    "FROM node_subdevices ORDER BY last_seen DESC"
                ).fetchall()
            )
        finally:
            conn.close()

    @staticmethod
    def _is_live(row_or_record, *, now: float) -> bool:
        """Accepts either a sqlite3.Row or a dict produced by ``_row_to_record``."""
        if isinstance(row_or_record, dict):
            last_seen = float(row_or_record["last_seen"])
            provenance = str(row_or_record.get("provenance") or "ble")
        else:
            last_seen = float(row_or_record["last_seen"])
            provenance = str(row_or_record["provenance"] or "ble")
        return (now - last_seen) <= liveness_window(provenance)

    @classmethod
    def _row_to_record(cls, row: sqlite3.Row, *, now: float) -> dict:
        try:
            attrs = json.loads(row["attrs"] or "{}")
            if not isinstance(attrs, dict):
                attrs = {}
        except (TypeError, ValueError):
            attrs = {}
        provenance = str(row["provenance"] or "ble")
        last_seen = float(row["last_seen"])
        live = (now - last_seen) <= liveness_window(provenance)
        return {
            "node_id": row["node_id"],
            "capability": row["capability"],
            "status": row["status"],
            "attrs": attrs,
            "provenance": provenance,
            "first_seen": float(row["first_seen"]),
            "last_seen": last_seen,
            "live": live,
            "liveness_window_s": liveness_window(provenance),
        }

    def _emit(self, event_name: str, payload: dict) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(event_name, payload)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("NodeSubdeviceStore on_change raised: %s", exc)
