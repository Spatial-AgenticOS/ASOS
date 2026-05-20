import os
import tempfile
import time
import asyncio

import pytest
import pytest_asyncio

from agents.taskflow import TaskFlowRuntime
from memory.store import MemoryStore


@pytest_asyncio.fixture
async def runtime():
    fd_mem, mem_path = tempfile.mkstemp(suffix=".db")
    os.close(fd_mem)
    fd_flow, flow_path = tempfile.mkstemp(suffix=".db")
    os.close(fd_flow)

    store = MemoryStore(db_path=mem_path)
    taskflow = TaskFlowRuntime(db_path=flow_path, memory_store=store)
    await taskflow.start()
    yield taskflow, store
    await taskflow.stop()

    os.unlink(mem_path)
    os.unlink(flow_path)


@pytest.mark.asyncio
async def test_taskflow_runs_steps_and_completes(runtime):
    taskflow, store = runtime
    flow = taskflow.create_flow(
        session_id="s1",
        title="simple flow",
        steps=[
            {"type": "noop"},
            {"type": "note.save", "content": "taskflow wrote this note"},
        ],
    )
    flow_id = flow["id"]

    deadline = time.time() + 5
    latest = flow
    while time.time() < deadline:
        latest = taskflow.get_flow(flow_id)
        if latest and latest["status"] == "completed":
            break
        await asyncio.sleep(0.1)

    assert latest is not None
    assert latest["status"] == "completed"
    notes = await store.search("taskflow wrote this note", limit=5)
    assert len(notes) >= 1


@pytest.mark.asyncio
async def test_taskflow_waiting_step_resumes(runtime):
    taskflow, _ = runtime
    flow = taskflow.create_flow(
        session_id="s2",
        title="wait flow",
        steps=[
            {"type": "sleep", "seconds": 1},
            {"type": "noop"},
        ],
    )
    flow_id = flow["id"]

    deadline = time.time() + 7
    latest = flow
    while time.time() < deadline:
        latest = taskflow.get_flow(flow_id)
        if latest and latest["status"] == "completed":
            break
        await asyncio.sleep(0.2)

    assert latest is not None
    assert latest["status"] == "completed"
