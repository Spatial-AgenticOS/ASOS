"""
FERAL Computer Use Tools
=========================
Core tools that make FERAL a real coding/system agent:
bash, read_file, write_file, edit_file, grep_search, glob_search, web_fetch.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict

from security.fetch_guard import html_to_markdown, safe_fetch
from security.sandbox_policy import SandboxPolicy
from skills.base import BaseSkill
from skills.impl import register_skill

MAX_OUTPUT = 50_000
BASH_TIMEOUT = 30
DANGEROUS_COMMANDS = re.compile(
    r"\b(rm\s+-rf\s+/|mkfs|dd\s+if=|:(){ :|fork\s*bomb|shutdown|reboot|halt|poweroff)\b",
    re.IGNORECASE,
)


def _check_shell_quotes(command: str) -> str | None:
    """Return an error string if shell quotes are unbalanced, else None."""
    in_single = False
    in_double = False
    i = 0
    while i < len(command):
        ch = command[i]
        if ch == '\\' and not in_single:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        i += 1
    if in_single or in_double:
        return (
            "Shell syntax error: unbalanced quotes in command. "
            "Tip: use computer_use__write_file to create files with "
            "arbitrary content instead of shell echo/printf."
        )
    return None


@register_skill
class ComputerUseSkill(BaseSkill):
    def __init__(self):
        super().__init__(skill_id="computer_use")
        self._sandbox_bash_enabled = os.getenv("FERAL_SANDBOX_BASH", "false").lower() in ("true", "1", "yes")
        self._policy: SandboxPolicy | None = None

    def _resolve_docker_sandbox(self):
        """Look up the Docker sandbox lazily so a daemon that started AFTER
        FERAL booted is still discoverable. Caching the handle at __init__
        froze a "no Docker" verdict for the entire process lifetime; this
        per-call resolution keeps the truth honest.
        """
        try:
            from security.docker_sandbox import get_sandbox
        except Exception:
            return None
        try:
            sandbox = get_sandbox()
        except Exception:
            return None
        if sandbox is None:
            return None
        try:
            available_attr = getattr(sandbox, "available", None)
            available = (
                bool(available_attr())
                if callable(available_attr)
                else bool(available_attr)
            )
        except Exception:
            available = False
        return sandbox if available else None

    def _get_policy(self) -> SandboxPolicy:
        if self._policy is None:
            self._policy = SandboxPolicy.load_default()
        return self._policy

    def _check_read(self, path_str: str) -> dict | None:
        policy = self._get_policy()
        if not policy.can_read_path(path_str):
            return {
                "success": False, "status_code": 403,
                "data": {"permission_needed": True, "path": path_str, "operation": "read"},
                "error": f"Permission denied: no read access to {path_str}. Grant access first.",
            }
        return None

    def _check_write(self, path_str: str) -> dict | None:
        policy = self._get_policy()
        if not policy.can_write_path(path_str):
            return {
                "success": False, "status_code": 403,
                "data": {"permission_needed": True, "path": path_str, "operation": "write"},
                "error": f"Permission denied: no write access to {path_str}. Grant access first.",
            }
        return None

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        dispatch = {
            "bash": self._bash,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "grep_search": self._grep_search,
            "glob_search": self._glob_search,
            "web_fetch": self._web_fetch,
            "index_folder": self._index_folder,
        }
        handler = dispatch.get(endpoint_id)
        if not handler:
            return {"success": False, "status_code": 404, "data": None, "error": f"Unknown endpoint: {endpoint_id}"}
        try:
            return await handler(args)
        except Exception as e:
            return {"success": False, "status_code": 500, "data": None, "error": str(e)}

    # ── bash ──────────────────────────────────────────────────────

    async def _bash(self, args: dict) -> dict:
        command = args.get("command", "")
        if not command:
            return {"success": False, "status_code": 400, "data": None, "error": "No command provided"}

        if DANGEROUS_COMMANDS.search(command):
            return {
                "success": False, "status_code": 403, "data": None,
                "error": f"Blocked potentially destructive command: {command}",
            }

        quote_err = _check_shell_quotes(command)
        if quote_err:
            return {"success": False, "status_code": 400, "data": None, "error": quote_err}

        timeout = min(int(args.get("timeout", BASH_TIMEOUT)), 120)

        # The executor flips this when the manifest declares
        # `requires_sandbox: true` on the bash endpoint. When it is set we
        # MUST refuse to run on the host — no silent degradation, no
        # success=True with `sandbox=host`.
        sandbox_required = bool(args.get("_feral_require_sandbox"))
        docker_sandbox = self._resolve_docker_sandbox() if (
            sandbox_required or self._sandbox_bash_enabled
        ) else None

        if docker_sandbox is not None:
            original_timeout = getattr(docker_sandbox, "_timeout", BASH_TIMEOUT)
            try:
                docker_sandbox._timeout = timeout
                result = await docker_sandbox.execute_shell(command)
            finally:
                docker_sandbox._timeout = original_timeout

            stdout = (result.get("stdout") or "")[:MAX_OUTPUT]
            stderr = (result.get("stderr") or "")[:MAX_OUTPUT]
            exit_code = int(result.get("exit_code", -1))
            success = bool(result.get("success"))
            data = {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "execution_time_ms": result.get("execution_time_ms"),
                "sandbox": "docker",
            }
            return {
                "success": success,
                "status_code": 200,
                "data": data,
                "error": stderr if not success else None,
            }

        if sandbox_required:
            # Manifest pins this endpoint behind the Docker sandbox; refuse
            # rather than leak a host execution under a "success" banner.
            return {
                "success": False,
                "status_code": 503,
                "data": {
                    "sandbox": "unavailable",
                    "permission_needed": False,
                    "setup_step": (
                        "Start Docker Desktop (or set up an alternative "
                        "sandbox) so computer_use__bash can run safely. "
                        "FERAL refuses to run shell commands on the host "
                        "when the manifest declares requires_sandbox=true."
                    ),
                },
                "error": (
                    "computer_use__bash requires the Docker sandbox but it "
                    "is not available. Refusing to fall back to host "
                    "execution."
                ),
            }

        sandbox_note = None
        if self._sandbox_bash_enabled and docker_sandbox is None:
            sandbox_note = "FERAL_SANDBOX_BASH is enabled but Docker sandbox is unavailable; executed on host."

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.environ.get("FERAL_CWD", None),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"success": False, "status_code": 408, "data": None, "error": f"Command timed out after {timeout}s"}

        stdout = stdout_b.decode(errors="replace")[:MAX_OUTPUT]
        stderr = stderr_b.decode(errors="replace")[:MAX_OUTPUT]

        return {
            "success": proc.returncode == 0,
            "status_code": 200,
            "data": {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "sandbox": "host",
                "note": sandbox_note,
            },
            "error": stderr if proc.returncode != 0 else None,
        }

    # ── read_file ─────────────────────────────────────────────────

    async def _read_file(self, args: dict) -> dict:
        path = Path(args.get("path", "")).expanduser()
        denied = self._check_read(str(path))
        if denied:
            return denied
        if not path.exists():
            return {"success": False, "status_code": 404, "data": None, "error": f"File not found: {path}"}
        if not path.is_file():
            return {"success": False, "status_code": 400, "data": None, "error": f"Not a file: {path}"}
        if path.stat().st_size > 2_000_000:
            return {"success": False, "status_code": 413, "data": None, "error": "File too large (>2MB). Use offset/limit."}

        text = path.read_text(errors="replace")
        lines = text.splitlines()

        offset = int(args.get("offset", 1)) - 1
        limit = int(args.get("limit", 0)) or len(lines)
        selected = lines[max(0, offset):offset + limit]

        numbered = "\n".join(f"{i + offset + 1:>6}|{line}" for i, line in enumerate(selected))

        return {
            "success": True,
            "status_code": 200,
            "data": {"path": str(path), "content": numbered, "total_lines": len(lines)},
            "error": None,
        }

    # ── write_file ────────────────────────────────────────────────

    async def _write_file(self, args: dict) -> dict:
        path = Path(args.get("path", "")).expanduser()
        content = args.get("content", "")
        if not str(path):
            return {"success": False, "status_code": 400, "data": None, "error": "No path provided"}
        denied = self._check_write(str(path))
        if denied:
            return denied

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

        return {
            "success": True,
            "status_code": 200,
            "data": {"path": str(path), "bytes_written": len(content.encode())},
            "error": None,
        }

    # ── edit_file ─────────────────────────────────────────────────

    async def _edit_file(self, args: dict) -> dict:
        path = Path(args.get("path", "")).expanduser()
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")

        denied = self._check_write(str(path))
        if denied:
            return denied
        if not path.exists():
            return {"success": False, "status_code": 404, "data": None, "error": f"File not found: {path}"}
        if not old_text:
            return {"success": False, "status_code": 400, "data": None, "error": "old_text is required"}

        content = path.read_text(errors="replace")
        count = content.count(old_text)
        if count == 0:
            return {"success": False, "status_code": 404, "data": None, "error": "old_text not found in file"}
        if count > 1:
            return {"success": False, "status_code": 409, "data": None, "error": f"old_text matches {count} locations — provide more context to be unique"}

        new_content = content.replace(old_text, new_text, 1)
        path.write_text(new_content)

        return {
            "success": True,
            "status_code": 200,
            "data": {"path": str(path), "replacements": 1},
            "error": None,
        }

    # ── grep_search ───────────────────────────────────────────────

    async def _grep_search(self, args: dict) -> dict:
        pattern = args.get("pattern", "")
        search_path = args.get("path", ".")
        include = args.get("include", "")

        if not pattern:
            return {"success": False, "status_code": 400, "data": None, "error": "No search pattern"}
        denied = self._check_read(search_path)
        if denied:
            return denied

        cmd = ["rg", "--line-number", "--no-heading", "--color=never", "-m", "50"]
        if include:
            cmd += ["--glob", include]
        cmd += ["--", pattern, search_path]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=15)
        except FileNotFoundError:
            return await self._grep_fallback(pattern, search_path, include)
        except asyncio.TimeoutError:
            return {"success": False, "status_code": 408, "data": None, "error": "Search timed out"}

        stdout = stdout_b.decode(errors="replace")[:MAX_OUTPUT]

        matches = []
        for line in stdout.strip().splitlines()[:200]:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append({"file": parts[0], "line": parts[1], "text": parts[2]})
            else:
                matches.append({"text": line})

        return {
            "success": True,
            "status_code": 200,
            "data": {"matches": matches, "total": len(matches)},
            "error": None,
        }

    async def _grep_fallback(self, pattern: str, search_path: str, include: str) -> dict:
        """Pure-Python fallback when ripgrep is not installed."""
        regex = re.compile(pattern)
        root = Path(search_path).expanduser()
        glob_pat = include or "**/*"
        matches = []

        for fp in root.glob(glob_pat):
            if not fp.is_file() or fp.stat().st_size > 1_000_000:
                continue
            try:
                for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                    if regex.search(line):
                        matches.append({"file": str(fp), "line": str(i), "text": line.strip()})
                        if len(matches) >= 200:
                            break
            except (PermissionError, OSError):
                continue
            if len(matches) >= 200:
                break

        return {
            "success": True,
            "status_code": 200,
            "data": {"matches": matches, "total": len(matches)},
            "error": None,
        }

    # ── glob_search ───────────────────────────────────────────────

    async def _glob_search(self, args: dict) -> dict:
        pattern = args.get("pattern", "")
        root = Path(args.get("path", ".")).expanduser()

        if not pattern:
            return {"success": False, "status_code": 400, "data": None, "error": "No glob pattern"}
        denied = self._check_read(str(root))
        if denied:
            return denied

        files = []
        for fp in root.glob(pattern):
            files.append(str(fp))
            if len(files) >= 500:
                break

        return {
            "success": True,
            "status_code": 200,
            "data": {"files": files, "total": len(files)},
            "error": None,
        }

    # ── web_fetch ─────────────────────────────────────────────────

    async def _web_fetch(self, args: dict) -> dict:
        url = args.get("url", "")
        max_length = int(args.get("max_length", 10_000))

        if not url:
            return {"success": False, "status_code": 400, "data": None, "error": "No URL provided"}

        result = await safe_fetch(url, timeout=15.0)
        if not result["success"]:
            code = int(result.get("status_code") or 400)
            err = result.get("error") or "fetch failed"
            return {"success": False, "status_code": code if code else 400, "data": None, "error": err}

        text = result["content"]
        content_type = result.get("content_type", "")
        if "html" in content_type.lower():
            text = html_to_markdown(text)

        return {
            "success": True,
            "status_code": 200,
            "data": {"url": url, "content": text[:max_length], "length": len(text)},
            "error": None,
        }

    # ── index_folder ──────────────────────────────────────────────

    _GITIGNORE_DIRS = frozenset({
        ".git", "__pycache__", "node_modules", ".tox", ".mypy_cache",
        ".pytest_cache", "dist", "build", ".next", ".nuxt", "venv", ".venv",
    })
    _MAX_INDEX_FILES = 500
    _MAX_INDEX_BYTES = 50 * 1024 * 1024

    async def _index_folder(self, args: dict) -> dict:
        root = Path(args.get("path", "")).expanduser().resolve()
        if not root.is_dir():
            return {"success": False, "status_code": 404, "data": None, "error": f"Not a directory: {root}"}
        denied = self._check_read(str(root))
        if denied:
            return denied

        tree_lines: list[str] = []
        summaries: list[str] = []
        total_bytes = 0
        file_count = 0

        gitignore_patterns: list[str] = []
        gi_path = root / ".gitignore"
        if gi_path.is_file():
            for line in gi_path.read_text(errors="replace").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    gitignore_patterns.append(stripped)

        def _should_skip(p: Path) -> bool:
            if p.name.startswith(".") and p.is_dir() and p.name != ".github":
                return True
            if p.name in self._GITIGNORE_DIRS:
                return True
            for pat in gitignore_patterns:
                try:
                    if p.match(pat):
                        return True
                except ValueError:
                    pass
            return False

        for dirpath, dirnames, filenames in os.walk(root):
            dp = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not _should_skip(dp / d)]
            rel = dp.relative_to(root)
            indent = "  " * len(rel.parts)

            for fname in sorted(filenames):
                if file_count >= self._MAX_INDEX_FILES or total_bytes >= self._MAX_INDEX_BYTES:
                    break
                fp = dp / fname
                if _should_skip(fp) or not fp.is_file():
                    continue
                fsize = fp.stat().st_size
                total_bytes += fsize
                file_count += 1
                tree_lines.append(f"{indent}{fname} ({fsize:,}B)")

                if fsize < 8192 and fsize > 0:
                    ext = fp.suffix.lower()
                    if ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".swift", ".rs", ".go",
                               ".md", ".txt", ".yaml", ".yml", ".toml", ".json", ".cfg", ".ini",
                               ".html", ".css", ".sh", ".sql"):
                        try:
                            head = fp.read_text(errors="replace")[:500]
                            summaries.append(f"--- {rel / fname} ---\n{head}")
                        except (PermissionError, OSError):
                            pass

            if file_count >= self._MAX_INDEX_FILES or total_bytes >= self._MAX_INDEX_BYTES:
                tree_lines.append("... (truncated)")
                break

        tree_text = f"Folder: {root}\nFiles: {file_count} | Size: {total_bytes:,}B\n\n" + "\n".join(tree_lines)
        summary_text = "\n\n".join(summaries[:60])

        return {
            "success": True,
            "status_code": 200,
            "data": {
                "path": str(root),
                "file_count": file_count,
                "total_bytes": total_bytes,
                "tree": tree_text,
                "file_previews": summary_text[:30_000],
            },
            "error": None,
        }
