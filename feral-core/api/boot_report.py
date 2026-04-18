"""Structured boot health report for FERAL Brain initialization."""
from __future__ import annotations
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("feral.boot")


class SubsystemStatus(str, Enum):
    OK = "ok"
    SKIPPED = "skipped"
    FAILED = "failed"
    DEGRADED = "degraded"


@dataclass
class SubsystemReport:
    name: str
    status: SubsystemStatus
    message: str = ""
    elapsed_ms: float = 0.0
    optional: bool = True


@dataclass
class BootReport:
    subsystems: list[SubsystemReport] = field(default_factory=list)
    total_elapsed_ms: float = 0.0
    current: Optional[str] = None

    def record(self, name: str, status: SubsystemStatus, message: str = "",
               elapsed_ms: float = 0.0, optional: bool = True):
        self.subsystems.append(SubsystemReport(
            name=name, status=status, message=message,
            elapsed_ms=elapsed_ms, optional=optional,
        ))

    def mark_degraded(self, name: str, message: str = ""):
        """Downgrade the most recent record for ``name`` to DEGRADED.

        Used when a subsystem started (no exception raised), but we've detected
        at runtime that it can't actually do useful work — e.g. DockerSandbox
        imported fine but Docker daemon isn't running.
        """
        for s in reversed(self.subsystems):
            if s.name == name:
                s.status = SubsystemStatus.DEGRADED
                if message:
                    s.message = message
                return
        self.record(name, SubsystemStatus.DEGRADED, message=message)

    @property
    def ok_count(self) -> int:
        return sum(1 for s in self.subsystems if s.status == SubsystemStatus.OK)

    @property
    def skipped_count(self) -> int:
        return sum(1 for s in self.subsystems if s.status == SubsystemStatus.SKIPPED)

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.subsystems if s.status == SubsystemStatus.FAILED)

    @property
    def degraded_count(self) -> int:
        return sum(1 for s in self.subsystems if s.status == SubsystemStatus.DEGRADED)

    def log_summary(self):
        logger.info("=" * 60)
        logger.info("FERAL Brain Boot Report")
        logger.info("=" * 60)
        icons = {"ok": "✓", "skipped": "○", "failed": "✗", "degraded": "⚠"}
        labels = {"ok": "OK", "skipped": "SKIP", "failed": "FAIL", "degraded": "DEGR"}
        for s in self.subsystems:
            icon = icons.get(s.status.value, "?")
            color_label = labels.get(s.status.value, s.status.value.upper())
            detail = f" — {s.message}" if s.message else ""
            ms = f" ({s.elapsed_ms:.0f}ms)" if s.elapsed_ms > 0 else ""
            logger.info(f"  {icon} [{color_label:4s}] {s.name}{ms}{detail}")
        logger.info("-" * 60)
        logger.info(
            f"  {self.ok_count} initialized, {self.degraded_count} degraded, "
            f"{self.skipped_count} skipped, {self.failed_count} failed "
            f"({self.total_elapsed_ms:.0f}ms total)"
        )
        logger.info("=" * 60)

    def to_dict(self) -> dict:
        return {
            "subsystems": [
                {"name": s.name, "status": s.status.value, "message": s.message, "elapsed_ms": s.elapsed_ms}
                for s in self.subsystems
            ],
            "current": self.current,
            "last": (
                {"name": self.subsystems[-1].name, "status": self.subsystems[-1].status.value}
                if self.subsystems else None
            ),
            "summary": {
                "ok": self.ok_count,
                "degraded": self.degraded_count,
                "skipped": self.skipped_count,
                "failed": self.failed_count,
                "total_ms": self.total_elapsed_ms,
            },
        }


@contextmanager
def boot_subsystem(report: BootReport, name: str, optional: bool = True):
    """Context manager that records subsystem boot status to the report."""
    start = time.time()
    report.current = name
    try:
        yield
        elapsed = (time.time() - start) * 1000
        report.record(name, SubsystemStatus.OK, elapsed_ms=elapsed, optional=optional)
    except ImportError as e:
        elapsed = (time.time() - start) * 1000
        report.record(name, SubsystemStatus.SKIPPED,
                      message=f"Missing dependency: {e}", elapsed_ms=elapsed, optional=optional)
        if not optional:
            raise
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        report.record(name, SubsystemStatus.FAILED,
                      message=str(e)[:200], elapsed_ms=elapsed, optional=optional)
        if not optional:
            raise
    finally:
        if report.current == name:
            report.current = None
