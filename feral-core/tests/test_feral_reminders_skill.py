from __future__ import annotations

import pytest

from skills.impl.feral_reminders import FeralRemindersSkill


@pytest.mark.asyncio
async def test_create_list_complete_delete_and_schedule(monkeypatch, tmp_path):
    monkeypatch.setenv("FERAL_HOME", str(tmp_path))
    skill = FeralRemindersSkill()

    created = await skill.execute(
        "create",
        {"values": {"title": "Buy milk", "due": "2026-05-02T09:00:00Z"}},
        {},
    )
    assert created["success"] is True
    reminder = created["data"]["reminder"]
    rid = reminder["id"]
    assert reminder["title"] == "Buy milk"

    listed = await skill.execute("list", {}, {})
    assert listed["success"] is True
    assert listed["data"]["count"] == 1
    assert listed["data"]["items"][0]["id"] == rid

    completed = await skill.execute("complete", {"id": rid}, {})
    assert completed["success"] is True
    assert completed["data"]["reminder"]["completed"] is True

    listed_open = await skill.execute("list", {}, {})
    assert listed_open["success"] is True
    assert listed_open["data"]["count"] == 0

    listed_all = await skill.execute("list", {"include_completed": True}, {})
    assert listed_all["success"] is True
    assert listed_all["data"]["count"] == 1

    scheduled = await skill.execute(
        "schedule_notification",
        {"id": rid, "when_iso": "2026-05-03T10:30:00Z"},
        {},
    )
    assert scheduled["success"] is True
    assert scheduled["data"]["scheduled"] is True

    deleted = await skill.execute("delete", {"id": rid}, {})
    assert deleted["success"] is True
    assert deleted["data"]["deleted_id"] == rid

    listed_final = await skill.execute("list", {"include_completed": True}, {})
    assert listed_final["success"] is True
    assert listed_final["data"]["count"] == 0
