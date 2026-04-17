"""Tool Genesis — agents that build their own tools from observed patterns."""
from __future__ import annotations
import ast
import json
import hashlib
import logging
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("feral.tool_genesis")

ALLOWED_IMPORTS = {
    "json", "math", "re", "datetime", "itertools", "functools",
    "collections", "statistics", "typing",
    "asyncio", "httpx",
}


def _ast_safety_check(code: str) -> tuple[bool, str]:
    """Return (safe, reason). Reject dangerous imports + exec/eval/compile/open/__import__."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [n.name.split(".")[0] for n in (node.names or [])]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
            for name in names:
                if name not in ALLOWED_IMPORTS:
                    return False, f"import not allowed: {name}"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in (
                "exec", "eval", "compile", "__import__", "open",
            ):
                return False, f"forbidden call: {node.func.id}"
            if isinstance(node.func, ast.Attribute) and node.func.attr in (
                "system", "popen", "spawn", "fork",
            ):
                return False, f"forbidden call: .{node.func.attr}"
    return True, "ok"

@dataclass
class ToolSequence:
    """A recorded sequence of tool calls."""
    tools: list[str]
    args_signature: str
    count: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

@dataclass
class GeneratedTool:
    """A tool auto-generated from observed patterns."""
    tool_id: str
    name: str
    description: str
    source_sequence: list[str]
    python_code: str
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    use_count: int = 0
    performance_vs_manual: float = 1.0  # ratio: generated/manual execution time
    requires_approval: bool = True
    approved: bool = False

SEQUENCE_THRESHOLD = 3  # how many times before proposing
RETIREMENT_DAYS = 30

class ToolGenesisEngine:
    def __init__(self, llm=None, db_path: Optional[str] = None):
        self._llm = llm
        self._sequences: dict[str, ToolSequence] = {}
        self._generated: dict[str, GeneratedTool] = {}
        self._session_traces: dict[str, list[dict]] = {}  # session -> recent tool calls
        self._db_path = db_path
        if db_path:
            self._init_db()
            self._load_from_db()

    def record_tool_call(self, session_id: str, tool_name: str, args: dict):
        trace = self._session_traces.setdefault(session_id, [])
        trace.append({"tool": tool_name, "args_keys": sorted(args.keys()), "ts": time.time()})
        if len(trace) > 50:
            trace[:] = trace[-50:]
        self._detect_sequences(session_id)

    def _detect_sequences(self, session_id: str):
        trace = self._session_traces.get(session_id, [])
        if len(trace) < 2:
            return
        for window in range(2, min(6, len(trace) + 1)):
            seq = [t["tool"] for t in trace[-window:]]
            sig = hashlib.md5(json.dumps(seq).encode()).hexdigest()[:12]
            if sig in self._sequences:
                self._sequences[sig].count += 1
                self._sequences[sig].last_seen = time.time()
            else:
                self._sequences[sig] = ToolSequence(tools=seq, args_signature=sig)
            self._persist_sequence(sig)

    def get_proposals(self) -> list[dict]:
        proposals = []
        for sig, seq in self._sequences.items():
            if seq.count >= SEQUENCE_THRESHOLD and sig not in self._generated:
                name = "_then_".join(t.split("__")[-1] for t in seq.tools[:3])
                proposals.append({
                    "sequence_id": sig,
                    "name": f"auto_{name}",
                    "tools": seq.tools,
                    "seen_count": seq.count,
                    "description": f"Composite tool combining {' → '.join(seq.tools)} (seen {seq.count}x)",
                })
        return proposals

    async def generate_tool(self, sequence_id: str) -> Optional[GeneratedTool]:
        seq = self._sequences.get(sequence_id)
        if not seq or not self._llm:
            return None

        prompt = (
            f"Generate a Python async function that combines these tool calls into one:\n"
            f"Sequence: {' → '.join(seq.tools)}\n\n"
            f"The function should:\n"
            f"1. Accept a single dict `args` parameter\n"
            f"2. Call each tool in sequence, passing results forward\n"
            f"3. Return a dict with 'success' bool and 'data' dict\n"
            f"4. Handle errors gracefully\n\n"
            f"Return ONLY valid Python code, no markdown."
        )

        try:
            response = await self._llm.chat([
                {"role": "system", "content": "You generate Python functions. Return only code."},
                {"role": "user", "content": prompt},
            ])
            text, _ = self._llm.extract_response(response)
            code = text.strip()

            safe, reason = _ast_safety_check(code)
            if not safe:
                logger.warning("Tool Genesis: AST safety check failed for %s: %s", sequence_id, reason)
                return None

            tool_id = f"genesis_{sequence_id}"
            name = f"auto_{'_then_'.join(t.split('__')[-1] for t in seq.tools[:3])}"

            tool = GeneratedTool(
                tool_id=tool_id,
                name=name,
                description=f"Auto-generated: {' → '.join(seq.tools)}",
                source_sequence=seq.tools,
                python_code=code,
                requires_approval=True,
                approved=False,
            )
            self._generated[sequence_id] = tool
            self._persist_generated(sequence_id)
            logger.info("Tool Genesis: created %s from sequence %s (pending approval)", tool_id, seq.tools)
            return tool
        except Exception as e:
            logger.warning(f"Tool Genesis generation failed: {e}")
            return None

    def approve_tool(self, tool_id: str) -> bool:
        """Mark a generated tool as approved for execution."""
        for sig, gt in self._generated.items():
            if gt.tool_id == tool_id:
                gt.approved = True
                self._persist_generated(sig)
                logger.info("Tool Genesis: approved %s", tool_id)
                return True
        return False

    async def execute_tool(self, tool_id: str, args: dict) -> dict:
        """Execute a generated tool in the sandbox. Must be approved first."""
        tool = None
        for gt in self._generated.values():
            if gt.tool_id == tool_id:
                tool = gt
                break
        if not tool:
            return {"success": False, "error": f"unknown tool: {tool_id}"}
        if tool.requires_approval and not tool.approved:
            return {"success": False, "error": "Tool must be approved first (call approve_tool)"}

        safe, reason = _ast_safety_check(tool.python_code)
        if not safe:
            return {"success": False, "error": f"safety check failed: {reason}"}

        try:
            from skills.impl.code_interpreter import _run_sandboxed
        except ImportError:
            _run_sandboxed = None

        if _run_sandboxed is None:
            return {"success": False, "error": "sandbox runtime not available"}

        import tempfile
        with tempfile.TemporaryDirectory() as work_dir:
            wrapper = f"{tool.python_code}\n\nimport json, sys\nresult = main({json.dumps(args)})\nprint(json.dumps(result))"
            result = await _run_sandboxed(wrapper, "python", work_dir, timeout=10)
        return {"success": result.get("exit_code") == 0, "output": result.get("stdout", ""), "error": result.get("stderr", "")}

    def record_usage(self, tool_id: str):
        for sig, gt in self._generated.items():
            if gt.tool_id == tool_id:
                gt.use_count += 1
                gt.last_used = time.time()
                self._persist_generated(sig)
                break

    def retire_unused(self) -> list[str]:
        now = time.time()
        cutoff = now - (RETIREMENT_DAYS * 86400)
        retired = []
        for sig, gt in list(self._generated.items()):
            if gt.last_used < cutoff and gt.last_used > 0:
                retired.append(gt.tool_id)
                del self._generated[sig]
                self._delete_generated(sig)
                logger.info(f"Tool Genesis: retired {gt.tool_id} (unused for {RETIREMENT_DAYS}d)")
        return retired

    def list_generated(self) -> list[dict]:
        return [
            {"tool_id": gt.tool_id, "name": gt.name, "description": gt.description,
             "source": gt.source_sequence, "use_count": gt.use_count,
             "created": gt.created_at, "last_used": gt.last_used}
            for gt in self._generated.values()
        ]

    def stats(self) -> dict:
        return {
            "sequences_tracked": len(self._sequences),
            "proposals_ready": len(self.get_proposals()),
            "tools_generated": len(self._generated),
            "total_uses": sum(gt.use_count for gt in self._generated.values()),
        }

    # ── SQLite persistence ──────────────────────

    def _init_db(self):
        con = sqlite3.connect(self._db_path)
        con.execute(
            "CREATE TABLE IF NOT EXISTS tool_sequences ("
            "  sig TEXT PRIMARY KEY,"
            "  tools_json TEXT NOT NULL,"
            "  args_signature TEXT NOT NULL,"
            "  count INTEGER NOT NULL DEFAULT 1,"
            "  first_seen REAL NOT NULL,"
            "  last_seen REAL NOT NULL"
            ")"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS generated_tools ("
            "  sig TEXT PRIMARY KEY,"
            "  tool_id TEXT NOT NULL,"
            "  name TEXT NOT NULL,"
            "  description TEXT NOT NULL,"
            "  source_sequence_json TEXT NOT NULL,"
            "  python_code TEXT NOT NULL,"
            "  created_at REAL NOT NULL,"
            "  last_used REAL NOT NULL DEFAULT 0,"
            "  use_count INTEGER NOT NULL DEFAULT 0,"
            "  performance_vs_manual REAL NOT NULL DEFAULT 1.0"
            ")"
        )
        con.commit()
        con.close()

    def _load_from_db(self):
        con = sqlite3.connect(self._db_path)
        for row in con.execute("SELECT sig, tools_json, args_signature, count, first_seen, last_seen FROM tool_sequences"):
            self._sequences[row[0]] = ToolSequence(
                tools=json.loads(row[1]), args_signature=row[2],
                count=row[3], first_seen=row[4], last_seen=row[5],
            )
        for row in con.execute(
            "SELECT sig, tool_id, name, description, source_sequence_json, python_code,"
            "       created_at, last_used, use_count, performance_vs_manual FROM generated_tools"
        ):
            self._generated[row[0]] = GeneratedTool(
                tool_id=row[1], name=row[2], description=row[3],
                source_sequence=json.loads(row[4]), python_code=row[5],
                created_at=row[6], last_used=row[7], use_count=row[8],
                performance_vs_manual=row[9],
            )
        con.close()
        logger.info("Tool Genesis DB loaded: %d sequences, %d generated", len(self._sequences), len(self._generated))

    def _persist_sequence(self, sig: str):
        if not self._db_path:
            return
        seq = self._sequences[sig]
        con = sqlite3.connect(self._db_path)
        con.execute(
            "INSERT OR REPLACE INTO tool_sequences (sig, tools_json, args_signature, count, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (sig, json.dumps(seq.tools), seq.args_signature, seq.count, seq.first_seen, seq.last_seen),
        )
        con.commit()
        con.close()

    def _persist_generated(self, sig: str):
        if not self._db_path:
            return
        gt = self._generated[sig]
        con = sqlite3.connect(self._db_path)
        con.execute(
            "INSERT OR REPLACE INTO generated_tools"
            " (sig, tool_id, name, description, source_sequence_json, python_code,"
            "  created_at, last_used, use_count, performance_vs_manual)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sig, gt.tool_id, gt.name, gt.description, json.dumps(gt.source_sequence),
             gt.python_code, gt.created_at, gt.last_used, gt.use_count, gt.performance_vs_manual),
        )
        con.commit()
        con.close()

    def _delete_generated(self, sig: str):
        if not self._db_path:
            return
        con = sqlite3.connect(self._db_path)
        con.execute("DELETE FROM generated_tools WHERE sig = ?", (sig,))
        con.commit()
        con.close()
