"""W18: process supervisor (overall + no-output timeouts, scope-cancel).

A Python, asyncio-native supervisor for spawning, timing-out, and
scope-cancelling external subprocesses (Codex CLI, Claude Code CLI,
ffmpeg, Ollama serve, etc.). The comparative analysis in
`docs/OPENCLAW_LESSONS.md` §2 + §10 W18 covers the lineage.

Public surface::

    from process.supervisor import create_process_supervisor

    supervisor = create_process_supervisor()
    handle = await supervisor.run(
        ["sleep", "10"],
        scope_key="batch-A",
        overall_timeout_sec=1.0,
    )
    record = await handle.wait()

The abstraction ships READY for W23/voice/Codex CLI/Claude Code CLI
integrations but is intentionally NOT wired into ``agents/orchestrator``
in this PR (no callers yet).

Cites docs/OPENCLAW_LESSONS.md §2 + §10 W18.
"""

from .registry import RunRecord, RunRegistry
from .supervisor import ProcessSupervisor, RunHandle, create_process_supervisor

__all__ = [
    "ProcessSupervisor",
    "RunHandle",
    "RunRecord",
    "RunRegistry",
    "create_process_supervisor",
]
