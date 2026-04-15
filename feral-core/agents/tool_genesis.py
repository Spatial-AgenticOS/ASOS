"""Tool Genesis — agents that build their own tools from observed patterns."""
from __future__ import annotations
import json
import hashlib
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("feral.tool_genesis")

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

SEQUENCE_THRESHOLD = 3  # how many times before proposing
RETIREMENT_DAYS = 30

class ToolGenesisEngine:
    def __init__(self, llm=None):
        self._llm = llm
        self._sequences: dict[str, ToolSequence] = {}
        self._generated: dict[str, GeneratedTool] = {}
        self._session_traces: dict[str, list[dict]] = {}  # session -> recent tool calls

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

            tool_id = f"genesis_{sequence_id}"
            name = f"auto_{'_then_'.join(t.split('__')[-1] for t in seq.tools[:3])}"

            tool = GeneratedTool(
                tool_id=tool_id,
                name=name,
                description=f"Auto-generated: {' → '.join(seq.tools)}",
                source_sequence=seq.tools,
                python_code=text.strip(),
            )
            self._generated[sequence_id] = tool
            logger.info(f"Tool Genesis: created {tool_id} from sequence {seq.tools}")
            return tool
        except Exception as e:
            logger.warning(f"Tool Genesis generation failed: {e}")
            return None

    def record_usage(self, tool_id: str):
        for gt in self._generated.values():
            if gt.tool_id == tool_id:
                gt.use_count += 1
                gt.last_used = time.time()

    def retire_unused(self) -> list[str]:
        now = time.time()
        cutoff = now - (RETIREMENT_DAYS * 86400)
        retired = []
        for sig, gt in list(self._generated.items()):
            if gt.last_used < cutoff and gt.last_used > 0:
                retired.append(gt.tool_id)
                del self._generated[sig]
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
