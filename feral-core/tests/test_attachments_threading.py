"""PR 10 gap-fill: TextCommandPayload.attachments flow through
api/server.py's text_command handler into the orchestrator context
and the working-memory transcript.

Pin the contract:
* ``payload.attachments`` is parsed (model dump) and inserted as
  ``context["attachments"]`` for the orchestrator.
* The user message pushed to working memory includes a human-readable
  attachment summary so the LLM transcript visibly carries the refs
  (not just hidden context).
* When no attachments are present, behaviour is unchanged.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from models.protocol import AttachmentRef, TextCommandPayload  # noqa: E402


def test_attachment_ref_optional_for_back_compat():
    """Existing clients that don't send attachments must still validate."""
    p = TextCommandPayload(text="hi")
    assert p.attachments is None
    dumped = p.model_dump()
    # `attachments` must serialise to None so clients that omit the
    # field don't see a different wire shape.
    assert dumped["attachments"] is None


def test_attachment_ref_payload_round_trip():
    ref = AttachmentRef(
        upload_id="abc", filename="report.pdf",
        content_type="application/pdf", size_bytes=1024, sha256="deadbeef",
    )
    p = TextCommandPayload(text="see file", attachments=[ref])
    dumped = p.model_dump()
    assert dumped["attachments"][0]["upload_id"] == "abc"
    assert dumped["attachments"][0]["filename"] == "report.pdf"


def test_server_text_command_handler_threads_attachments_into_context():
    """The actual server module imports many heavy deps, so we don't
    spin it up. Instead we verify by source-grep that the handler now
    explicitly threads attachments into ``ctx`` and the working-memory
    push. This pins the wiring against silent reverts."""
    import api.server as server_mod

    src = inspect.getsource(server_mod)
    # The handler must read payload.attachments
    assert "payload.attachments" in src, (
        "text_command handler does not reference payload.attachments — "
        "PR 10 wiring regressed."
    )
    # The handler must inject attachments into the orchestrator context
    assert "ctx[\"attachments\"]" in src or "ctx['attachments']" in src, (
        "Attachments are not threaded into orchestrator context."
    )
    # The handler must surface the attachment summary in the user
    # message text so the model transcript shows it.
    assert "attached files" in src, (
        "User-visible attachment summary missing from working memory push."
    )
