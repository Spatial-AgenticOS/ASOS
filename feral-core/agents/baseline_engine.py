"""
FERAL Baseline Learning Engine v1
====================================
Analyzes user patterns over time and detects anomalies / drift from
normal behaviour.  Every recorded metric maintains a rolling window of
recent values; the engine computes running mean and standard-deviation
and can flag:

  * **anomaly**  — single value deviates > N sigma from the baseline
  * **trend**    — sustained upward/downward movement over a window
  * **milestone** — user hit a personal record or round-number goal

All baselines are persisted in a lightweight SQLite store so they
survive restarts.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("feral.baseline")


@dataclass
class BaselineMetric:
    metric_id: str
    category: str = "general"
    values: list[float] = field(default_factory=list)
    window_size: int = 14
    mean: float = 0.0
    std_dev: float = 0.0
    last_updated: float = 0.0


@dataclass
class BaselineAlert:
    metric_id: str
    alert_type: Literal["anomaly", "trend", "milestone"]
    severity: Literal["info", "warning", "critical"]
    message: str
    current_value: float
    baseline_mean: float
    deviation_sigma: float
    timestamp: float = field(default_factory=time.time)


class BaselineEngine:
    """SQLite-backed baseline learning engine.

    Records metric observations, maintains rolling statistics, and
    exposes anomaly / trend detection for the proactive engine.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS baselines (
        metric_id   TEXT PRIMARY KEY,
        category    TEXT NOT NULL DEFAULT 'general',
        values_json TEXT NOT NULL DEFAULT '[]',
        mean        REAL NOT NULL DEFAULT 0,
        std_dev     REAL NOT NULL DEFAULT 0,
        window_size INTEGER NOT NULL DEFAULT 14,
        updated_at  REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS baseline_alerts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_id   TEXT NOT NULL,
        alert_type  TEXT NOT NULL,
        severity    TEXT NOT NULL,
        message     TEXT NOT NULL,
        current_val REAL NOT NULL,
        baseline_mean REAL NOT NULL,
        deviation_sigma REAL NOT NULL,
        ts          REAL NOT NULL
    );
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = ":memory:"
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._DDL)
        self._alert_listeners: list = []

    def on_alert(self, callback) -> None:
        """Register a listener that fires every time an alert is persisted.

        Listeners receive the :class:`BaselineAlert` instance. Failures in
        individual callbacks are swallowed so one broken listener can't
        suppress subsequent ones or corrupt anomaly detection.
        """
        self._alert_listeners.append(callback)

    def record(
        self,
        metric_id: str,
        value: float,
        category: str = "general",
        window_size: int = 14,
    ) -> None:
        """Add a data point and recompute rolling statistics."""
        row = self._conn.execute(
            "SELECT values_json, window_size FROM baselines WHERE metric_id = ?",
            (metric_id,),
        ).fetchone()

        if row:
            values: list[float] = json.loads(row["values_json"])
            ws = row["window_size"]
        else:
            values = []
            ws = window_size

        values.append(value)
        if len(values) > ws:
            values = values[-ws:]

        mean = statistics.mean(values) if values else 0.0
        std = statistics.pstdev(values) if len(values) >= 2 else 0.0

        self._conn.execute(
            """INSERT INTO baselines (metric_id, category, values_json, mean, std_dev, window_size, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(metric_id) DO UPDATE SET
                   category    = excluded.category,
                   values_json = excluded.values_json,
                   mean        = excluded.mean,
                   std_dev     = excluded.std_dev,
                   updated_at  = excluded.updated_at
            """,
            (metric_id, category, json.dumps(values), mean, std, ws, time.time()),
        )
        self._conn.commit()

    def get_baseline(self, metric_id: str) -> Optional[BaselineMetric]:
        row = self._conn.execute(
            "SELECT * FROM baselines WHERE metric_id = ?", (metric_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_metric(row)

    def get_all_baselines(self) -> list[BaselineMetric]:
        rows = self._conn.execute("SELECT * FROM baselines ORDER BY updated_at DESC").fetchall()
        return [self._row_to_metric(r) for r in rows]

    def check_anomaly(
        self,
        metric_id: str,
        current_value: float,
        threshold_sigma: float = 2.0,
    ) -> Optional[BaselineAlert]:
        """Return an alert if *current_value* deviates beyond *threshold_sigma*."""
        metric = self.get_baseline(metric_id)
        if metric is None or len(metric.values) < 3 or metric.std_dev == 0:
            return None

        deviation = abs(current_value - metric.mean) / metric.std_dev
        if deviation < threshold_sigma:
            return None

        if deviation >= 3.0:
            severity: Literal["info", "warning", "critical"] = "critical"
        elif deviation >= 2.0:
            severity = "warning"
        else:
            severity = "info"

        direction = "above" if current_value > metric.mean else "below"
        alert = BaselineAlert(
            metric_id=metric_id,
            alert_type="anomaly",
            severity=severity,
            message=(
                f"{metric_id} is {current_value:.1f}, which is {deviation:.1f}σ "
                f"{direction} your baseline of {metric.mean:.1f}"
            ),
            current_value=current_value,
            baseline_mean=metric.mean,
            deviation_sigma=deviation,
        )
        self._persist_alert(alert)
        return alert

    def check_trend(
        self, metric_id: str, window: int = 7
    ) -> Optional[BaselineAlert]:
        """Detect a consistent upward or downward trend over the last *window* values."""
        metric = self.get_baseline(metric_id)
        if metric is None or len(metric.values) < window:
            return None

        tail = metric.values[-window:]
        diffs = [tail[i + 1] - tail[i] for i in range(len(tail) - 1)]

        if all(d > 0 for d in diffs):
            direction = "upward"
        elif all(d < 0 for d in diffs):
            direction = "downward"
        else:
            return None

        total_shift = tail[-1] - tail[0]
        sigma = abs(total_shift / metric.std_dev) if metric.std_dev else 0.0

        alert = BaselineAlert(
            metric_id=metric_id,
            alert_type="trend",
            severity="warning" if sigma >= 1.5 else "info",
            message=(
                f"{metric_id} shows a consistent {direction} trend over the "
                f"last {window} readings ({tail[0]:.1f} → {tail[-1]:.1f})"
            ),
            current_value=tail[-1],
            baseline_mean=metric.mean,
            deviation_sigma=sigma,
        )
        self._persist_alert(alert)
        return alert

    def get_alerts(self, since: float | None = None) -> list[BaselineAlert]:
        if since is None:
            since = time.time() - 86400  # last 24 h
        rows = self._conn.execute(
            "SELECT * FROM baseline_alerts WHERE ts >= ? ORDER BY ts DESC",
            (since,),
        ).fetchall()
        return [
            BaselineAlert(
                metric_id=r["metric_id"],
                alert_type=r["alert_type"],
                severity=r["severity"],
                message=r["message"],
                current_value=r["current_val"],
                baseline_mean=r["baseline_mean"],
                deviation_sigma=r["deviation_sigma"],
                timestamp=r["ts"],
            )
            for r in rows
        ]

    def summary(self) -> dict:
        metrics_count = self._conn.execute("SELECT count(*) c FROM baselines").fetchone()["c"]
        recent_alerts = self._conn.execute(
            "SELECT count(*) c FROM baseline_alerts WHERE ts >= ?",
            (time.time() - 86400,),
        ).fetchone()["c"]
        cats = self._conn.execute(
            "SELECT DISTINCT category FROM baselines"
        ).fetchall()
        return {
            "metrics_tracked": metrics_count,
            "recent_alerts": recent_alerts,
            "categories": [r["category"] for r in cats],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_metric(row: sqlite3.Row) -> BaselineMetric:
        return BaselineMetric(
            metric_id=row["metric_id"],
            category=row["category"],
            values=json.loads(row["values_json"]),
            window_size=row["window_size"],
            mean=row["mean"],
            std_dev=row["std_dev"],
            last_updated=row["updated_at"],
        )

    def _persist_alert(self, alert: BaselineAlert) -> None:
        self._conn.execute(
            """INSERT INTO baseline_alerts
               (metric_id, alert_type, severity, message,
                current_val, baseline_mean, deviation_sigma, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alert.metric_id,
                alert.alert_type,
                alert.severity,
                alert.message,
                alert.current_value,
                alert.baseline_mean,
                alert.deviation_sigma,
                alert.timestamp,
            ),
        )
        self._conn.commit()
        for listener in list(self._alert_listeners):
            try:
                listener(alert)
            except Exception as exc:
                logger.debug("Baseline alert listener failed: %s", exc)
