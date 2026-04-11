"""
FERAL Code Interpreter Skill
=============================
Run Python/Node snippets and capture generated artifacts (CSV/images/etc.).
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

from config.loader import feral_data_home
from skills.base import BaseSkill
from skills.impl import register_skill

MAX_OUTPUT = 80_000
MAX_ARTIFACTS = 25
MAX_INLINE_IMAGE_BYTES = 2_000_000
MAX_INLINE_TEXT_BYTES = 200_000
TEXT_EXTS = {".txt", ".md", ".csv", ".tsv", ".json", ".html", ".xml", ".log"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


@register_skill
class CodeInterpreterSkill(BaseSkill):
    def __init__(self):
        super().__init__(skill_id="code_interpreter")
        default_artifacts_root = feral_data_home() / "artifacts"
        self._artifacts_root = Path(
            os.getenv("FERAL_ARTIFACTS_DIR", str(default_artifacts_root))
        ).expanduser()

    async def execute(self, endpoint_id: str, args: Dict[str, Any], vault: Dict[str, str]) -> Dict[str, Any]:
        _ = vault
        if endpoint_id == "run_python":
            return await self._run_code("python", args)
        if endpoint_id == "run_node":
            return await self._run_code("node", args)
        return {
            "success": False,
            "status_code": 404,
            "data": None,
            "error": f"Unknown endpoint: {endpoint_id}",
        }

    async def _run_code(self, language: str, args: dict) -> dict:
        code = str(args.get("code", "") or "")
        if not code.strip():
            return {"success": False, "status_code": 400, "data": None, "error": "code is required"}

        timeout = max(1, min(int(args.get("timeout", 45) or 45), 300))
        run_id = str(uuid.uuid4())[:10]
        temp_dir = Path(tempfile.mkdtemp(prefix=f"feral_code_{run_id}_"))
        script_name = "main.py" if language == "python" else "main.js"
        script_path = temp_dir / script_name
        script_path.write_text(code, encoding="utf-8")

        argv = ["python3", script_name] if language == "python" else ["node", script_name]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(temp_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout = (stdout_b or b"").decode(errors="replace")[:MAX_OUTPUT]
            stderr = (stderr_b or b"").decode(errors="replace")[:MAX_OUTPUT]
            exit_code = proc.returncode if proc.returncode is not None else -1
            artifacts = self._collect_artifacts(temp_dir, script_name=script_name, run_id=run_id)
            return {
                "success": exit_code == 0,
                "status_code": 200,
                "data": {
                    "language": language,
                    "run_id": run_id,
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                    "artifact_count": len(artifacts),
                    "artifacts": artifacts,
                    "artifact_dir": str(self._artifacts_root / run_id) if artifacts else None,
                },
                "error": stderr if exit_code != 0 else None,
            }
        except asyncio.TimeoutError:
            artifacts = self._collect_artifacts(temp_dir, script_name=script_name, run_id=run_id)
            return {
                "success": False,
                "status_code": 408,
                "data": {
                    "language": language,
                    "run_id": run_id,
                    "artifact_count": len(artifacts),
                    "artifacts": artifacts,
                    "artifact_dir": str(self._artifacts_root / run_id) if artifacts else None,
                },
                "error": f"Execution timed out after {timeout}s",
            }
        except FileNotFoundError as e:
            return {
                "success": False,
                "status_code": 500,
                "data": None,
                "error": str(e),
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _collect_artifacts(self, run_dir: Path, *, script_name: str, run_id: str) -> list[dict]:
        artifacts: list[dict] = []
        out_dir = self._artifacts_root / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        for file_path in sorted(run_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.name == script_name:
                continue
            rel = file_path.relative_to(run_dir)
            dest = out_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest)

            size = dest.stat().st_size
            ext = dest.suffix.lower()
            mime = mimetypes.guess_type(dest.name)[0] or "application/octet-stream"
            entry: dict[str, Any] = {
                "name": str(rel),
                "path": str(dest),
                "size_bytes": size,
                "mime_type": mime,
                "kind": "binary",
            }

            if ext in IMAGE_EXTS:
                entry["kind"] = "image"
                if size <= MAX_INLINE_IMAGE_BYTES:
                    entry["b64"] = base64.b64encode(dest.read_bytes()).decode("ascii")
            elif ext in TEXT_EXTS:
                entry["kind"] = "text" if ext in {".txt", ".md", ".log"} else "data"
                if size <= MAX_INLINE_TEXT_BYTES:
                    entry["text_preview"] = dest.read_text(errors="replace")[:20_000]

            artifacts.append(entry)
            if len(artifacts) >= MAX_ARTIFACTS:
                break

        return artifacts
