"""Tests for agents/tool_genesis.py — AST safety, approval gate, sandbox execution."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.tool_genesis import (
    ALLOWED_IMPORTS,
    GeneratedTool,
    ToolGenesisEngine,
    _ast_safety_check,
)


# ── AST safety check: rejections ────────────────────────────────────────────

class TestASTSafetyRejects:
    def test_os_system(self):
        ok, reason = _ast_safety_check("import os\nos.system('rm -rf /')")
        assert not ok
        assert "os" in reason

    def test_exec_call(self):
        ok, reason = _ast_safety_check("exec('print(1)')")
        assert not ok
        assert "exec" in reason

    def test_eval_call(self):
        ok, reason = _ast_safety_check("x = eval('1+1')")
        assert not ok
        assert "eval" in reason

    def test_dunder_import(self):
        ok, reason = _ast_safety_check("__import__('os')")
        assert not ok
        assert "__import__" in reason

    def test_subprocess(self):
        ok, reason = _ast_safety_check("import subprocess\nsubprocess.run(['ls'])")
        assert not ok
        assert "subprocess" in reason

    def test_open_file(self):
        ok, reason = _ast_safety_check("f = open('/etc/passwd')")
        assert not ok
        assert "open" in reason

    def test_compile_call(self):
        ok, reason = _ast_safety_check("compile('x=1', '', 'exec')")
        assert not ok
        assert "compile" in reason

    def test_popen(self):
        ok, reason = _ast_safety_check("import os\nos.popen('ls')")
        assert not ok
        assert "os" in reason

    def test_syntax_error(self):
        ok, reason = _ast_safety_check("def (broken:")
        assert not ok
        assert "syntax" in reason.lower()


# ── AST safety check: allowed code ──────────────────────────────────────────

class TestASTSafetyAccepts:
    def test_import_json(self):
        ok, reason = _ast_safety_check("import json\ndata = json.loads('{}')")
        assert ok
        assert reason == "ok"

    def test_simple_function(self):
        code = "import math\ndef compute(x): return math.sqrt(x)"
        ok, reason = _ast_safety_check(code)
        assert ok

    def test_httpx_allowed(self):
        code = "import httpx\nasync def fetch(url): return await httpx.AsyncClient().get(url)"
        ok, reason = _ast_safety_check(code)
        assert ok

    def test_all_allowed_imports(self):
        for mod in ALLOWED_IMPORTS:
            ok, _ = _ast_safety_check(f"import {mod}")
            assert ok, f"import {mod} should be allowed"


# ── Approval gate ────────────────────────────────────────────────────────────

class TestApprovalGate:
    def _make_engine_with_tool(self):
        engine = ToolGenesisEngine()
        tool = GeneratedTool(
            tool_id="genesis_test1",
            name="auto_test",
            description="test tool",
            source_sequence=["a", "b"],
            python_code="import json\ndef main(args): return {'ok': True}",
            requires_approval=True,
            approved=False,
        )
        engine._generated["test1"] = tool
        return engine

    @pytest.mark.asyncio
    async def test_unapproved_tool_rejected(self):
        engine = self._make_engine_with_tool()
        result = await engine.execute_tool("genesis_test1", {})
        assert not result["success"]
        assert "approved" in result["error"].lower()

    def test_approve_then_execute(self):
        engine = self._make_engine_with_tool()
        assert engine.approve_tool("genesis_test1") is True
        tool = engine._generated["test1"]
        assert tool.approved is True

    def test_approve_unknown_tool(self):
        engine = ToolGenesisEngine()
        assert engine.approve_tool("nonexistent") is False


# ── Sandbox execution (mocked) ──────────────────────────────────────────────

class TestSandboxExecution:
    @pytest.mark.asyncio
    async def test_approved_tool_calls_sandbox(self):
        engine = ToolGenesisEngine()
        tool = GeneratedTool(
            tool_id="genesis_sandbox",
            name="auto_sandbox",
            description="sandbox test",
            source_sequence=["x"],
            python_code="import json\ndef main(args): return {'ok': True}",
            requires_approval=True,
            approved=True,
        )
        engine._generated["sandbox"] = tool

        mock_result = {"exit_code": 0, "stdout": '{"ok": true}', "stderr": ""}
        with patch("skills.impl.code_interpreter._run_sandboxed", new_callable=AsyncMock, return_value=mock_result) as mock_sandbox:
            result = await engine.execute_tool("genesis_sandbox", {"key": "value"})
            mock_sandbox.assert_called_once()
            assert result["success"]

    @pytest.mark.asyncio
    async def test_generate_tool_rejects_unsafe_code(self):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value={"choices": [{"message": {"content": "import os\nos.system('ls')"}}]})
        mock_llm.extract_response = MagicMock(return_value=("import os\nos.system('ls')", []))

        engine = ToolGenesisEngine(llm=mock_llm)
        engine._sequences["seq1"] = MagicMock(tools=["a__b", "c__d"], count=5)

        tool = await engine.generate_tool("seq1")
        assert tool is None
