"""
FERAL Supervisor-Aware Process Management
==========================================
Detects the process supervisor (systemd, launchd, Docker, or none),
manages the PID file, and provides graceful-shutdown hooks.

Key principle: "Don't fight the supervisor."  If a supervisor owns
restarts, FERAL exits cleanly and lets it respawn.  Only in bare-metal
mode does FERAL attempt self-restart.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("feral.infra.supervisor")

_DEFAULT_PID_PATH = Path.home() / ".feral" / "brain.pid"


class SupervisorKind(Enum):
    NONE = "none"
    SYSTEMD = "systemd"
    LAUNCHD = "launchd"
    DOCKER = "docker"


@dataclass
class SupervisorInfo:
    kind: SupervisorKind = SupervisorKind.NONE
    managed_restart: bool = False
    container_id: str = ""


def detect_supervisor() -> SupervisorInfo:
    """Detect which supervisor (if any) is managing this process."""
    if _is_docker():
        cid = _read_container_id()
        return SupervisorInfo(
            kind=SupervisorKind.DOCKER,
            managed_restart=True,
            container_id=cid,
        )

    if _is_systemd():
        return SupervisorInfo(kind=SupervisorKind.SYSTEMD, managed_restart=True)

    if _is_launchd():
        return SupervisorInfo(kind=SupervisorKind.LAUNCHD, managed_restart=True)

    return SupervisorInfo(kind=SupervisorKind.NONE, managed_restart=False)


def _is_docker() -> bool:
    return (
        os.path.isfile("/.dockerenv")
        or os.environ.get("container") == "docker"
    )


def _read_container_id() -> str:
    try:
        cgroup = Path("/proc/self/cgroup")
        if cgroup.exists():
            text = cgroup.read_text()
            for line in text.splitlines():
                if "docker" in line or "containerd" in line:
                    return line.rstrip().rsplit("/", 1)[-1][:12]
    except OSError:
        pass
    return os.environ.get("HOSTNAME", "")[:12]


def _is_systemd() -> bool:
    return (
        os.environ.get("INVOCATION_ID") is not None
        or os.getppid() == 1
        and Path("/run/systemd/system").is_dir()
    )


def _is_launchd() -> bool:
    if sys.platform != "darwin":
        return False
    return os.environ.get("XPC_SERVICE_NAME") is not None


# ---------------------------------------------------------------------------
# PID file management
# ---------------------------------------------------------------------------

def _pid_is_alive(pid: int) -> bool:
    """Check whether a process with the given PID is running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_pid_file(path: Optional[Path] = None) -> Path:
    """
    Write the current PID to *path*, cleaning a stale file first.

    Raises ``RuntimeError`` if another live process already holds the lock.
    """
    path = path or _DEFAULT_PID_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            existing_pid = int(path.read_text().strip())
        except (ValueError, OSError):
            existing_pid = -1

        if _pid_is_alive(existing_pid) and existing_pid != os.getpid():
            raise RuntimeError(
                f"Another FERAL process is running (PID {existing_pid}). "
                f"Remove {path} manually if this is stale."
            )
        logger.info("Cleaning stale PID file (was PID %d)", existing_pid)
        path.unlink(missing_ok=True)

    path.write_text(str(os.getpid()))
    atexit.register(_release_pid_file, path)
    logger.info("PID file acquired: %s (PID %d)", path, os.getpid())
    return path


def _release_pid_file(path: Path) -> None:
    try:
        if path.exists():
            stored = int(path.read_text().strip())
            if stored == os.getpid():
                path.unlink(missing_ok=True)
                logger.debug("PID file released: %s", path)
    except (ValueError, OSError):
        pass


# ---------------------------------------------------------------------------
# Graceful shutdown hooks
# ---------------------------------------------------------------------------

_shutdown_hooks: list[Callable[[], None]] = []
_shutdown_triggered = False


def register_shutdown_hook(fn: Callable[[], None]) -> None:
    """Register a callback that runs on graceful shutdown (SIGTERM/SIGINT)."""
    _shutdown_hooks.append(fn)


def _run_shutdown_hooks(signum: int, _frame) -> None:
    global _shutdown_triggered
    if _shutdown_triggered:
        return
    _shutdown_triggered = True

    sig_name = signal.Signals(signum).name
    logger.info("Received %s — running %d shutdown hooks", sig_name, len(_shutdown_hooks))

    for hook in _shutdown_hooks:
        try:
            hook()
        except Exception as exc:
            logger.warning("Shutdown hook %s failed: %s", hook.__name__, exc)

    sys.exit(0)


def install_signal_handlers() -> None:
    """Install SIGTERM/SIGINT handlers that run registered shutdown hooks."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _run_shutdown_hooks)
    logger.debug("Signal handlers installed for SIGTERM, SIGINT")


# ---------------------------------------------------------------------------
# Restart logic
# ---------------------------------------------------------------------------

def request_restart(info: Optional[SupervisorInfo] = None) -> None:
    """
    Request a process restart in a supervisor-aware way.

    - Under a supervisor: exit cleanly and let the supervisor respawn.
    - Bare-metal: re-exec the current process.
    """
    info = info or detect_supervisor()

    if info.managed_restart:
        logger.info(
            "Supervisor (%s) manages restarts — exiting cleanly",
            info.kind.value,
        )
        sys.exit(0)

    logger.info("No supervisor detected — re-execing process")
    os.execv(sys.executable, [sys.executable] + sys.argv)
