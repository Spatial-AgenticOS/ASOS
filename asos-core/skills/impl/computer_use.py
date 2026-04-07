"""
THEORA Computer Use Tools
=========================
Core tools that make THEORA a real coding/system agent:
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
from skills.base import BaseSkill
from skills.impl import register_skill

MAX_OUTPUT = 50_000
BASH_TIMEOUT = 30
DANGEROUS_COMMANDS = re.compile(
    r"\b(rm\s+-rf\s+/|mkfs|dd\s+if=|:(){ :|fork\s*bomb|shutdown|reboot|halt|poweroff)\b",
    re.IGNORECASE,
)


@register_skill
class ComputerUseSkill(BaseSkill):
    def __init__(self):
        super().__init__(skill_id="computer_use")

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        dispatch = {
            "bash": self._bash,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "grep_search": self._grep_search,
            "glob_search": self._glob_search,
            "web_fetch": self._web_fetch,
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

        timeout = min(int(args.get("timeout", BASH_TIMEOUT)), 120)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.environ.get("THEORA_CWD", None),
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
            },
            "error": stderr if proc.returncode != 0 else None,
        }

    # ── read_file ─────────────────────────────────────────────────

    async def _read_file(self, args: dict) -> dict:
        path = Path(args.get("path", "")).expanduser()
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
