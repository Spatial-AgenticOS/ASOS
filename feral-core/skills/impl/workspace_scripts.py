"""
Workspace Scripts — the FERAL never-say-no escape hatch.

Writes ad-hoc scripts to ~/.feral/workspace/scripts/, executes them in the
Docker sandbox when available (falls back to host subprocess with a short
timeout when Docker is not running), and maintains a catalog.json so past
successful scripts are reusable on later turns.

This is the OpenClaw-equivalent `exec` surface, but persistent and
indexable: the agent can rerun or compose past scripts instead of always
generating new ones.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from config.loader import feral_home
from skills.base import BaseSkill
from skills.impl import register_skill

logger = logging.getLogger("feral.skill.workspace_scripts")


def _scripts_dir() -> Path:
    d = feral_home() / "workspace" / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _catalog_path() -> Path:
    return _scripts_dir() / "catalog.json"


def _load_catalog() -> Dict[str, Any]:
    p = _catalog_path()
    if not p.exists():
        return {"scripts": []}
    try:
        return json.loads(p.read_text() or "{}") or {"scripts": []}
    except Exception:
        return {"scripts": []}


def _save_catalog(cat: Dict[str, Any]) -> None:
    try:
        _catalog_path().write_text(json.dumps(cat, indent=2))
    except Exception as exc:
        logger.warning("catalog save failed: %s", exc)


_EXT_MAP = {"python": ".py", "bash": ".sh", "node": ".js"}


@register_skill
class WorkspaceScriptsSkill(BaseSkill):
    def __init__(self):
        super().__init__("workspace_scripts")

    async def execute(
        self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]
    ) -> Dict[str, Any]:
        if endpoint_id == "run":
            return await self._run(args)
        if endpoint_id == "list_catalog":
            return self._list_catalog()
        if endpoint_id == "rerun":
            return await self._rerun(args)
        if endpoint_id == "delete":
            return self._delete(args)
        return {"success": False, "status_code": 400, "data": None, "error": f"Unknown endpoint {endpoint_id!r}"}

    # ------------------------------------------------------------------

    async def _run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        language = (args.get("language") or "python").lower().strip()
        code = args.get("code") or ""
        name = (args.get("name") or "").strip() or f"script_{int(time.time())}"
        timeout = int(args.get("timeout") or 30)
        forwarded_args = args.get("args") or ""
        if language not in _EXT_MAP:
            return {"success": False, "status_code": 400, "data": None,
                    "error": f"Unsupported language {language!r} (python|bash|node)"}
        if not code.strip():
            return {"success": False, "status_code": 400, "data": None, "error": "code is required"}

        script_id = uuid.uuid4().hex[:12]
        ext = _EXT_MAP[language]
        script_path = _scripts_dir() / f"{script_id}{ext}"
        try:
            script_path.write_text(code, encoding="utf-8")
            script_path.chmod(0o644)
        except Exception as exc:
            return {"success": False, "status_code": 500, "data": None, "error": f"write failed: {exc}"}

        exec_result = await self._execute_script(language, script_path, timeout, forwarded_args)
        catalog_entry = None
        if exec_result.get("exit_code") == 0:
            catalog_entry = self._record_success(script_id, name, language, script_path, args)

        return {
            "success": exec_result.get("exit_code") == 0,
            "status_code": 200 if exec_result.get("exit_code") == 0 else 500,
            "data": {
                "script_id": script_id,
                "name": name,
                "language": language,
                "path": str(script_path),
                "stdout": exec_result.get("stdout", "")[:8000],
                "stderr": exec_result.get("stderr", "")[:4000],
                "exit_code": exec_result.get("exit_code"),
                "catalog_entry": catalog_entry,
                "sandboxed": exec_result.get("sandboxed", False),
            },
            "error": exec_result.get("stderr") if exec_result.get("exit_code") else None,
        }

    async def _rerun(self, args: Dict[str, Any]) -> Dict[str, Any]:
        script_id = (args.get("script_id") or "").strip()
        if not script_id:
            return {"success": False, "status_code": 400, "data": None, "error": "script_id required"}
        cat = _load_catalog()
        entry = next((e for e in cat["scripts"] if e.get("id") == script_id), None)
        if not entry:
            return {"success": False, "status_code": 404, "data": None, "error": f"No script {script_id}"}
        path = Path(entry.get("path") or "")
        if not path.exists():
            return {"success": False, "status_code": 410, "data": None, "error": "Script file no longer exists"}
        language = entry.get("language") or "python"
        timeout = int(args.get("timeout") or 30)
        forwarded_args = args.get("args") or ""
        exec_result = await self._execute_script(language, path, timeout, forwarded_args)
        entry["last_run"] = int(time.time())
        entry["runs"] = int(entry.get("runs") or 0) + 1
        _save_catalog(cat)
        return {
            "success": exec_result.get("exit_code") == 0,
            "status_code": 200 if exec_result.get("exit_code") == 0 else 500,
            "data": {
                "script_id": script_id,
                "stdout": exec_result.get("stdout", "")[:8000],
                "stderr": exec_result.get("stderr", "")[:4000],
                "exit_code": exec_result.get("exit_code"),
            },
            "error": exec_result.get("stderr") if exec_result.get("exit_code") else None,
        }

    def _list_catalog(self) -> Dict[str, Any]:
        cat = _load_catalog()
        return {"success": True, "status_code": 200, "data": {"scripts": cat.get("scripts") or []}, "error": None}

    def _delete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        script_id = (args.get("script_id") or "").strip()
        if not script_id:
            return {"success": False, "status_code": 400, "data": None, "error": "script_id required"}
        cat = _load_catalog()
        remaining = []
        removed = None
        for e in cat.get("scripts") or []:
            if e.get("id") == script_id:
                removed = e
            else:
                remaining.append(e)
        if not removed:
            return {"success": False, "status_code": 404, "data": None, "error": f"No script {script_id}"}
        try:
            Path(removed.get("path") or "").unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
        cat["scripts"] = remaining
        _save_catalog(cat)
        return {"success": True, "status_code": 200, "data": {"deleted": True, "id": script_id}, "error": None}

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_script(
        self, language: str, path: Path, timeout: int, forwarded_args: str
    ) -> Dict[str, Any]:
        try:
            from api.state import state
            sandbox = getattr(state, "sandbox", None) or getattr(state, "docker_sandbox", None)
            if sandbox and sandbox.available():
                code_text = path.read_text()
                result = await sandbox.execute(code_text, language=language)
                return {
                    "stdout": result.get("stdout", ""),
                    "stderr": result.get("stderr", ""),
                    "exit_code": result.get("exit_code", -1),
                    "sandboxed": True,
                }
        except Exception as exc:
            logger.debug("sandbox execute failed, falling back to host: %s", exc)

        return await self._run_on_host(language, path, timeout, forwarded_args)

    @staticmethod
    async def _run_on_host(
        language: str, path: Path, timeout: int, forwarded_args: str
    ) -> Dict[str, Any]:
        env = dict(os.environ)
        if forwarded_args:
            env["FERAL_ARGS"] = forwarded_args
        if language == "python":
            argv = ["python3", str(path)]
        elif language == "bash":
            argv = ["bash", str(path)]
        elif language == "node":
            argv = ["node", str(path)]
        else:
            return {"stdout": "", "stderr": f"Unsupported language {language!r}", "exit_code": -1, "sandboxed": False}

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": (stdout or b"").decode("utf-8", errors="replace"),
                "stderr": (stderr or b"").decode("utf-8", errors="replace"),
                "exit_code": proc.returncode or 0,
                "sandboxed": False,
            }
        except asyncio.TimeoutError:
            return {"stdout": "", "stderr": f"timeout after {timeout}s", "exit_code": 124, "sandboxed": False}
        except FileNotFoundError as exc:
            return {"stdout": "", "stderr": f"interpreter not found: {exc}", "exit_code": 127, "sandboxed": False}
        except Exception as exc:
            return {"stdout": "", "stderr": f"host run failed: {exc}", "exit_code": 1, "sandboxed": False}

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    @staticmethod
    def _record_success(
        script_id: str, name: str, language: str, path: Path, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        cat = _load_catalog()
        entry = {
            "id": script_id,
            "name": name,
            "language": language,
            "path": str(path),
            "created_at": int(time.time()),
            "last_run": int(time.time()),
            "runs": 1,
            "args_hint": args.get("args") or "",
        }
        cat.setdefault("scripts", []).append(entry)
        _save_catalog(cat)
        return entry
