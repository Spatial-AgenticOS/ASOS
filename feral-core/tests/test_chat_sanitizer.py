"""Tests for outbound assistant-text sanitizer (A1)."""

from agents.chat_sanitizer import sanitize_assistant_display_text


class TestSanitizer:
    def test_strips_eom_sentinel(self):
        assert sanitize_assistant_display_text("Hello<|eom|>") == "Hello"
        assert sanitize_assistant_display_text("<|end_of_turn|>done") == "done"

    def test_strips_multiple_control_tokens(self):
        text = "a<|eot_id|>b<|start_header_id|>c<|eom|>"
        assert sanitize_assistant_display_text(text) == "abc"

    def test_strips_full_tool_call_block(self):
        text = (
            "Before <tool_calls>\n"
            "  <invoke name=\"shell\">do stuff</invoke>\n"
            "</tool_calls> After"
        )
        out = sanitize_assistant_display_text(text)
        assert "<tool_calls>" not in out
        assert "</tool_calls>" not in out
        assert "invoke" not in out.lower()
        assert "Before" in out and "After" in out

    def test_strips_orphan_closing_tag(self):
        text = "Some prose.</tool_calls>"
        assert sanitize_assistant_display_text(text) == "Some prose."

    def test_strips_function_call_tag(self):
        text = "Intro <function_call>{\"name\":\"x\"}</function_call> outro"
        out = sanitize_assistant_display_text(text)
        assert "function_call" not in out
        assert "Intro" in out and "outro" in out

    def test_strips_invoke_blob(self):
        text = 'thinking… invoke[{"name":"shell","arguments":{"cmd":"ls"}}] done'
        out = sanitize_assistant_display_text(text)
        assert "invoke" not in out.lower()
        assert "thinking" in out and "done" in out

    def test_preserves_normal_prose(self):
        text = "Hello world — how are you? (no residue here)"
        assert sanitize_assistant_display_text(text) == text

    def test_preserves_markdown_code_blocks(self):
        text = "```python\nprint('hi')\n```"
        assert sanitize_assistant_display_text(text) == text

    def test_preserves_mathlike_inequalities(self):
        # ``<|`` literally is the sentinel trigger, but bare "<" or "|>"
        # without the sentinel pattern must not be stripped.
        text = "if a < 5 and b > 3 then …"
        assert sanitize_assistant_display_text(text) == text

    def test_empty_and_none_safe(self):
        assert sanitize_assistant_display_text("") == ""
        assert sanitize_assistant_display_text(None) is None  # type: ignore[arg-type]

    def test_trailing_function_marker(self):
        text = "Final answer.\nFUNCTION"
        out = sanitize_assistant_display_text(text)
        assert "FUNCTION" not in out
        assert "Final answer." in out

    def test_pure_residue_becomes_empty(self):
        text = "<|eom|></tool_calls>"
        assert sanitize_assistant_display_text(text).strip() == ""
