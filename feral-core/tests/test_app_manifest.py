"""Contract tests for AppManifest — the third-party app manifest."""

from __future__ import annotations

import copy

import pytest

from models.app_manifest import (
    ActionSpec,
    AppManifest,
    DataSchemaSpec,
    InteractionRules,
    JobSpec,
    NotificationSchema,
    SurfaceSpec,
)
from models.skill_manifest import BrandProfile


def _minimal_manifest(**overrides):
    """Build a syntactically correct manifest with one authored surface."""

    base = {
        "app_id": "feral-messages",
        "version": "1.0.0",
        "author": "feral-team",
        "description": "Tiny example messaging app",
        "brand": BrandProfile(name="Messages", primary_color="#22C55E"),
        "permissions": ["storage"],
        "data_schemas": [
            DataSchemaSpec(
                schema_id="thread",
                schema={"type": "object", "properties": {"contact_id": {"type": "string"}}},
            ),
            DataSchemaSpec(
                schema_id="send_message_payload",
                schema={"type": "object", "required": ["text"]},
            ),
        ],
        "surfaces": [
            SurfaceSpec(
                surface_id="inbox",
                title="Inbox",
                kind="authored",
                template_root={
                    "type": "VStack",
                    "children": [
                        {"type": "Text", "value": "Inbox"},
                        {"type": "Button", "label": "Open thread", "action_id": "open_thread"},
                    ],
                },
                action_contract=[
                    ActionSpec(action_id="open_thread", handler="navigate", target="thread"),
                ],
            ),
            SurfaceSpec(
                surface_id="thread",
                title="Thread",
                kind="authored",
                template_root={
                    "type": "VStack",
                    "children": [
                        {"type": "Text", "value": "$data.contact_id"},
                        {"type": "Button", "label": "Send", "action_id": "send_message"},
                    ],
                },
                action_contract=[
                    ActionSpec(
                        action_id="send_message",
                        handler="app_event",
                        value_schema_ref="#/data_schemas/send_message_payload",
                    ),
                ],
                data_schema_ref="thread",
            ),
        ],
        "entry_surface_id": "inbox",
    }
    base.update(overrides)
    return AppManifest(**base)


class TestRoundTrip:
    def test_minimal_manifest_round_trips(self):
        m = _minimal_manifest()
        data = m.model_dump()
        rebuilt = AppManifest(**data)
        assert rebuilt.app_id == m.app_id
        assert len(rebuilt.surfaces) == 2
        assert rebuilt.entry_surface_id == "inbox"

    def test_get_surface_and_schema_helpers(self):
        m = _minimal_manifest()
        assert m.get_surface("inbox").surface_id == "inbox"
        assert m.get_surface("bogus") is None
        assert m.get_data_schema("thread").schema_id == "thread"
        assert m.get_data_schema("bogus") is None


class TestAppIdValidation:
    @pytest.mark.parametrize(
        "bad",
        [
            "",                 # empty
            "ab",               # too short
            "Feral-Messages",   # uppercase
            "feral_messages",   # underscore not allowed
            "-leading-dash",    # must start with a letter
            "1abc",             # must start with a letter
            "a" * 65,           # too long
            "contains space",
        ],
    )
    def test_rejects_bad_app_id(self, bad):
        with pytest.raises(Exception):
            _minimal_manifest(app_id=bad)

    @pytest.mark.parametrize(
        "good",
        ["feral-messages", "foo", "abc-123-def", "a" * 64],
    )
    def test_accepts_good_app_id(self, good):
        m = _minimal_manifest(app_id=good)
        assert m.app_id == good


class TestCrossRefs:
    def test_entry_surface_must_exist(self):
        with pytest.raises(Exception) as exc:
            _minimal_manifest(entry_surface_id="not-a-surface")
        assert "entry_surface_id" in str(exc.value)

    def test_authored_requires_template_root(self):
        surfaces = [
            SurfaceSpec(
                surface_id="inbox",
                kind="authored",
                template_root=None,
                action_contract=[],
            ),
        ]
        with pytest.raises(Exception) as exc:
            _minimal_manifest(surfaces=surfaces, entry_surface_id="inbox")
        assert "template_root" in str(exc.value)

    def test_hybrid_requires_template_root(self):
        surfaces = [
            SurfaceSpec(
                surface_id="home",
                kind="hybrid",
                template_root=None,
                generation_prompt="build a welcome surface",
                action_contract=[],
            ),
        ]
        with pytest.raises(Exception):
            _minimal_manifest(surfaces=surfaces, entry_surface_id="home")

    def test_generated_requires_generation_prompt(self):
        surfaces = [
            SurfaceSpec(
                surface_id="home",
                kind="generated",
                template_root=None,
                generation_prompt="",
                action_contract=[],
            ),
        ]
        with pytest.raises(Exception) as exc:
            _minimal_manifest(surfaces=surfaces, entry_surface_id="home")
        assert "generation_prompt" in str(exc.value)

    def test_generated_requires_non_empty_interactions(self):
        # Override interactions to be truly empty
        empty_rules = InteractionRules(
            button_style_priority=[],
            destructive_confirmation_required=False,
            list_render_preference="auto",
            prose_guidance="",
            forbidden_components=[],
            accessibility_notes=[],
        )
        surfaces = [
            SurfaceSpec(
                surface_id="home",
                kind="generated",
                template_root=None,
                generation_prompt="generate home",
                action_contract=[],
            ),
        ]
        with pytest.raises(Exception) as exc:
            _minimal_manifest(
                surfaces=surfaces,
                entry_surface_id="home",
                interactions=empty_rules,
            )
        assert "interactions" in str(exc.value)

    def test_action_id_in_template_must_be_in_contract(self):
        bad_surface = SurfaceSpec(
            surface_id="inbox",
            kind="authored",
            template_root={
                "type": "Button",
                "action_id": "do_something_nefarious",
            },
            action_contract=[],
        )
        with pytest.raises(Exception) as exc:
            _minimal_manifest(
                surfaces=[bad_surface],
                entry_surface_id="inbox",
            )
        assert "action_contract" in str(exc.value)
        assert "do_something_nefarious" in str(exc.value)

    def test_navigate_action_target_must_be_valid_surface(self):
        bad = SurfaceSpec(
            surface_id="inbox",
            kind="authored",
            template_root={"type": "Button", "action_id": "nav"},
            action_contract=[
                ActionSpec(action_id="nav", handler="navigate", target="not-real"),
            ],
        )
        with pytest.raises(Exception) as exc:
            _minimal_manifest(surfaces=[bad], entry_surface_id="inbox")
        assert "not-real" in str(exc.value)

    def test_unknown_data_schema_ref_rejected(self):
        bad = SurfaceSpec(
            surface_id="inbox",
            kind="authored",
            template_root={"type": "Text", "value": "hi"},
            data_schema_ref="bogus",
            action_contract=[],
        )
        with pytest.raises(Exception) as exc:
            _minimal_manifest(surfaces=[bad], entry_surface_id="inbox")
        assert "bogus" in str(exc.value)

    def test_unknown_value_schema_ref_in_action_rejected(self):
        bad = SurfaceSpec(
            surface_id="inbox",
            kind="authored",
            template_root={"type": "Button", "action_id": "send"},
            action_contract=[
                ActionSpec(
                    action_id="send",
                    handler="app_event",
                    value_schema_ref="#/data_schemas/not-a-schema",
                ),
            ],
        )
        with pytest.raises(Exception) as exc:
            _minimal_manifest(surfaces=[bad], entry_surface_id="inbox")
        assert "not-a-schema" in str(exc.value)


class TestUniqueness:
    def test_rejects_duplicate_surface_id(self):
        s1 = SurfaceSpec(
            surface_id="dup",
            kind="authored",
            template_root={"type": "Text"},
            action_contract=[],
        )
        s2 = SurfaceSpec(
            surface_id="dup",
            kind="authored",
            template_root={"type": "Text"},
            action_contract=[],
        )
        with pytest.raises(Exception):
            _minimal_manifest(surfaces=[s1, s2], entry_surface_id="dup")

    def test_rejects_duplicate_schema_id(self):
        schemas = [
            DataSchemaSpec(schema_id="dup", schema={"type": "object"}),
            DataSchemaSpec(schema_id="dup", schema={"type": "object"}),
        ]
        with pytest.raises(Exception):
            _minimal_manifest(data_schemas=schemas)

    def test_rejects_duplicate_job_id(self):
        jobs = [JobSpec(job_id="j"), JobSpec(job_id="j")]
        with pytest.raises(Exception):
            _minimal_manifest(background_jobs=jobs)


class TestNotifications:
    def test_notification_deep_link_must_be_valid_surface(self):
        bad_notif = NotificationSchema(default_deep_link_surface_id="nope")
        with pytest.raises(Exception) as exc:
            _minimal_manifest(notifications=bad_notif)
        assert "nope" in str(exc.value)

    def test_notifications_valid_surface_accepted(self):
        m = _minimal_manifest(
            notifications=NotificationSchema(default_deep_link_surface_id="thread"),
        )
        assert m.notifications.default_deep_link_surface_id == "thread"


class TestActionIdValidation:
    @pytest.mark.parametrize(
        "bad",
        ["", "has space", "@bad", "-leading"],
    )
    def test_rejects_bad_action_id(self, bad):
        with pytest.raises(Exception):
            ActionSpec(action_id=bad)

    @pytest.mark.parametrize(
        "good",
        ["send", "open_thread", "nav:home", "fooBar-1"],
    )
    def test_accepts_good_action_id(self, good):
        a = ActionSpec(action_id=good)
        assert a.action_id == good


class TestInteractionRules:
    def test_system_prompt_chunk_mentions_destructive(self):
        rules = InteractionRules()
        chunk = rules.to_system_prompt_chunk()
        assert "destructive" in chunk.lower()

    def test_forbidden_components_shown_in_prompt(self):
        rules = InteractionRules(forbidden_components=["Table", "CodeBlock"])
        chunk = rules.to_system_prompt_chunk()
        assert "Table" in chunk and "CodeBlock" in chunk

    def test_prose_guidance_preserved(self):
        rules = InteractionRules(prose_guidance="never show raw IDs")
        chunk = rules.to_system_prompt_chunk()
        assert "never show raw IDs" in chunk
