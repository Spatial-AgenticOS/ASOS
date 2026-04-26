"""W18: spawn-adapter implementations for the process supervisor.

Two adapters mirror openclaw's split:

* :mod:`process.supervisor.adapters.child` — plain
  ``asyncio.create_subprocess_exec`` (stdout + stderr piped, no TTY).
  Use this for every well-behaved CLI that does NOT check ``isatty``.
* :mod:`process.supervisor.adapters.pty` — ``pty.openpty`` + raw
  ``os.fork`` + ``os.execvp`` so the child sees a real controlling
  terminal. Required for Codex CLI / Claude Code CLI / any tool that
  refuses to render TUI output without ``isatty(stdout) == True``.

Cites docs/OPENCLAW_LESSONS.md §2 + §10 W18.
"""
