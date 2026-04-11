"""Tests for filesystem permission enforcement, routines scheduler, and taskflow new step types."""

import json
import os
import tempfile
import time

import pytest
import pytest_asyncio

from security.sandbox_policy import SandboxPolicy
from agents.scheduler import CronService, JobType, _compute_next_run
from agents.taskflow import TaskFlowRuntime
from memory.store import MemoryStore


# ─────────────────────────────────────────────
# Filesystem Permission Tests
# ─────────────────────────────────────────────


class TestPathPermissions:
    def test_default_read_within_feral_home(self, tmp_path):
        policy = SandboxPolicy({
            "version": "1.0",
            "name": "test",
            "filesystem": {
                "read_paths": [str(tmp_path / "allowed")],
                "write_paths": [str(tmp_path / "writable")],
                "blocked_paths": [str(tmp_path / "secret")],
            },
        })
        (tmp_path / "allowed").mkdir()
        assert policy.can_read_path(str(tmp_path / "allowed" / "file.txt")) is True

    def test_read_denied_outside_allowed(self, tmp_path):
        policy = SandboxPolicy({
            "version": "1.0",
            "name": "test",
            "filesystem": {
                "read_paths": [str(tmp_path / "allowed")],
                "write_paths": [],
                "blocked_paths": [],
            },
        })
        assert policy.can_read_path(str(tmp_path / "other" / "file.txt")) is False

    def test_write_denied_read_only_path(self, tmp_path):
        policy = SandboxPolicy({
            "version": "1.0",
            "name": "test",
            "filesystem": {
                "read_paths": [str(tmp_path / "readable")],
                "write_paths": [],
                "blocked_paths": [],
            },
        })
        assert policy.can_write_path(str(tmp_path / "readable" / "file.txt")) is False

    def test_blocked_path_overrides_allowed(self, tmp_path):
        blocked = tmp_path / "data" / "secret"
        allowed = tmp_path / "data"
        policy = SandboxPolicy({
            "version": "1.0",
            "name": "test",
            "filesystem": {
                "read_paths": [str(allowed)],
                "write_paths": [str(allowed)],
                "blocked_paths": [str(blocked)],
            },
        })
        assert policy.can_read_path(str(blocked / "key.pem")) is False
        assert policy.can_write_path(str(blocked / "key.pem")) is False

    def test_grant_folder_persists(self, tmp_path, monkeypatch):
        monkeypatch.setattr("security.sandbox_policy.feral_home", lambda: tmp_path)
        policy = SandboxPolicy({
            "version": "1.0",
            "name": "test",
            "filesystem": {
                "read_paths": [],
                "write_paths": [],
                "blocked_paths": [],
            },
        })
        target = tmp_path / "project"
        target.mkdir()
        assert policy.can_read_path(str(target / "main.py")) is False

        result = policy.grant_folder(str(target), mode="readwrite")
        assert result["ok"] is True

        assert policy.can_read_path(str(target / "main.py")) is True
        assert policy.can_write_path(str(target / "main.py")) is True

    def test_grant_folder_read_only_prevents_write(self, tmp_path, monkeypatch):
        monkeypatch.setattr("security.sandbox_policy.feral_home", lambda: tmp_path)
        policy = SandboxPolicy({
            "version": "1.0",
            "name": "test",
            "filesystem": {
                "read_paths": [],
                "write_paths": [],
                "blocked_paths": [],
            },
        })
        target = tmp_path / "readonly_project"
        target.mkdir()
        policy.grant_folder(str(target), mode="read")
        assert policy.can_read_path(str(target / "file.txt")) is True
        assert policy.can_write_path(str(target / "file.txt")) is False

    def test_revoke_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr("security.sandbox_policy.feral_home", lambda: tmp_path)
        policy = SandboxPolicy({
            "version": "1.0",
            "name": "test",
            "filesystem": {
                "read_paths": [],
                "write_paths": [],
                "blocked_paths": [],
            },
        })
        target = tmp_path / "revoketest"
        target.mkdir()
        policy.grant_folder(str(target), mode="read")
        assert policy.can_read_path(str(target / "a.txt")) is True

        policy.revoke_folder(str(target))
        assert policy.can_read_path(str(target / "a.txt")) is False

    def test_list_grants(self, tmp_path, monkeypatch):
        monkeypatch.setattr("security.sandbox_policy.feral_home", lambda: tmp_path)
        policy = SandboxPolicy({
            "version": "1.0",
            "name": "test",
            "filesystem": {
                "read_paths": [],
                "write_paths": [],
                "blocked_paths": [],
            },
        })
        target = tmp_path / "listed"
        target.mkdir()
        policy.grant_folder(str(target), mode="readwrite")
        grants = policy.list_grants()
        assert len(grants) >= 1
        assert any(g["mode"] == "readwrite" for g in grants)

    def test_grant_blocked_path_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr("security.sandbox_policy.feral_home", lambda: tmp_path)
        policy = SandboxPolicy({
            "version": "1.0",
            "name": "test",
            "filesystem": {
                "read_paths": [],
                "write_paths": [],
                "blocked_paths": [str(tmp_path / "nope")],
            },
        })
        result = policy.grant_folder(str(tmp_path / "nope"), mode="read")
        assert result["ok"] is False


# ─────────────────────────────────────────────
# Routines Scheduler Tests
# ─────────────────────────────────────────────


class TestRoutinesScheduler:
    @pytest.fixture()
    def svc(self, tmp_path):
        db = str(tmp_path / "test_sched.db")
        return CronService(db_path=db)

    def test_create_and_list(self, svc):
        job = svc.create_job(JobType.SCHEDULED, "every 5m", "test", {}, "s1")
        assert job.id is not None
        assert job.job_type == JobType.SCHEDULED
        jobs = svc.list_jobs()
        assert any(j.id == job.id for j in jobs)

    def test_extended_job_types(self, svc):
        for jt in (JobType.TRIGGERED, JobType.CHAIN, JobType.WATCHER):
            job = svc.create_job(jt, "every 1m", f"test {jt.value}", {}, "s1")
            assert job.job_type == jt

    def test_pause_and_resume(self, svc):
        job = svc.create_job(JobType.SCHEDULED, "every 10m", "pausable", {}, "s1")
        assert job.enabled is True
        svc.pause_job(job.id)
        updated = svc.get_job(job.id)
        assert updated.enabled is False
        svc.resume_job(job.id)
        updated = svc.get_job(job.id)
        assert updated.enabled is True

    def test_run_history(self, svc):
        job = svc.create_job(JobType.SCHEDULED, "every 1m", "with runs", {}, "s1")
        run_id = svc.record_run_start(job.id)
        assert run_id > 0
        svc.record_run_finish(run_id, "success", {"output": "ok"})
        runs = svc.get_runs(job.id)
        assert len(runs) == 1
        assert runs[0]["status"] == "success"
        assert runs[0]["result"]["output"] == "ok"

    def test_get_job(self, svc):
        job = svc.create_job(JobType.CUSTOM, "every 30m", "lookup", {}, "s1")
        found = svc.get_job(job.id)
        assert found is not None
        assert found.description == "lookup"
        assert svc.get_job(99999) is None

    def test_delete_cleans_up(self, svc):
        job = svc.create_job(JobType.SCHEDULED, "every 1m", "deletable", {}, "s1")
        assert svc.delete_job(job.id) is True
        assert svc.get_job(job.id) is None


# ─────────────────────────────────────────────
# TaskFlow New Step Types
# ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def taskflow_runtime(tmp_path):
    mem_path = str(tmp_path / "mem.db")
    flow_path = str(tmp_path / "flow.db")
    store = MemoryStore(db_path=mem_path)
    runtime = TaskFlowRuntime(db_path=flow_path, memory_store=store)
    await runtime.start()
    yield runtime, store
    await runtime.stop()


@pytest.mark.asyncio
async def test_condition_step_truthy(taskflow_runtime):
    runtime, store = taskflow_runtime
    flow = runtime.create_flow(
        session_id="cond-test",
        title="condition test",
        context={"flag": True},
        steps=[
            {"type": "condition", "field": "flag", "op": "truthy", "then": "branch_a", "else": "branch_b"},
        ],
    )
    assert flow["id"]
    import asyncio
    for _ in range(20):
        f = runtime.get_flow(flow["id"])
        if f and f["status"] == "completed":
            break
        await asyncio.sleep(0.2)

    final = runtime.get_flow(flow["id"])
    assert final["status"] == "completed"
    step = final["steps"][0]
    assert step["result"]["match"] is True
    assert step["result"]["branch"] == "branch_a"


@pytest.mark.asyncio
async def test_condition_step_eq(taskflow_runtime):
    runtime, store = taskflow_runtime
    flow = runtime.create_flow(
        session_id="eq-test",
        title="eq condition",
        context={"mode": "prod"},
        steps=[
            {"type": "condition", "field": "mode", "op": "eq", "value": "prod", "then": "deploy", "else": "skip"},
        ],
    )
    import asyncio
    for _ in range(20):
        f = runtime.get_flow(flow["id"])
        if f and f["status"] == "completed":
            break
        await asyncio.sleep(0.2)

    final = runtime.get_flow(flow["id"])
    assert final["status"] == "completed"
    assert final["steps"][0]["result"]["match"] is True


@pytest.mark.asyncio
async def test_skill_invoke_missing_skill(taskflow_runtime):
    runtime, store = taskflow_runtime
    flow = runtime.create_flow(
        session_id="skill-test",
        title="skill invoke test",
        steps=[
            {"type": "skill.invoke", "skill_id": "nonexistent", "endpoint": "run"},
        ],
    )
    import asyncio
    for _ in range(20):
        f = runtime.get_flow(flow["id"])
        if f and f["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.2)

    final = runtime.get_flow(flow["id"])
    assert final["status"] == "failed"


# ─────────────────────────────────────────────
# Protocol Tests
# ─────────────────────────────────────────────


class TestProtocolPermissionTypes:
    def test_permission_request_in_registry(self):
        from models.protocol import MESSAGE_TYPES
        assert "permission_request" in MESSAGE_TYPES
        assert "permission_response" in MESSAGE_TYPES

    def test_permission_request_payload(self):
        from models.protocol import PermissionRequestPayload
        p = PermissionRequestPayload(path="/home/user/code", operation="read", reason="need access")
        assert p.path == "/home/user/code"
        assert p.operation == "read"

    def test_permission_response_payload(self):
        from models.protocol import PermissionResponsePayload
        p = PermissionResponsePayload(request_id="abc123", granted=True, mode="readwrite")
        assert p.granted is True
        assert p.mode == "readwrite"


# ─────────────────────────────────────────────
# Cron Computation
# ─────────────────────────────────────────────


class TestCronCompute:
    def test_every_minutes(self):
        now = time.time()
        nxt = _compute_next_run("every 5m", now)
        assert nxt == pytest.approx(now + 300, abs=1)

    def test_every_hours(self):
        now = time.time()
        nxt = _compute_next_run("every 2h", now)
        assert nxt == pytest.approx(now + 7200, abs=1)

    def test_daily(self):
        now = time.time()
        nxt = _compute_next_run("daily 09:00", now)
        assert nxt > now
