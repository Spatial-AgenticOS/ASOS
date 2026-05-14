"""Tests for cli/ui_kit — the shared InquirerPy + Rich primitives.

Covers:

* The non-interactive fallback path (numeric select, plain text,
  silent password) which is what pytest itself drives because the
  test runner is never a TTY.
* The brand chrome (raccoon emoji + brand colour) renders even when
  Rich is missing — it must never raise.
* The masked-character path is gated on TTY + InquirerPy availability;
  we only assert the behaviour we can verify here (the silent fallback
  reads from getpass when stdin is non-tty).
"""

from __future__ import annotations

import io
import sys

import pytest

from cli import ui_kit


# ---------------------------------------------------------------------------
# Brand chrome
# ---------------------------------------------------------------------------


class TestBrandChrome:
    def test_brand_emoji_is_raccoon(self):
        assert ui_kit.BRAND_EMOJI == "🦝"
        assert ui_kit.BRAND_COLOR == "cyan"

    def test_brand_panel_renders_without_rich(self, monkeypatch, capsys):
        monkeypatch.setattr(ui_kit, "_RICH_AVAILABLE", False)
        monkeypatch.setattr(ui_kit, "Panel", None)
        ui_kit.brand_panel("hello", body="world")
        captured = capsys.readouterr()
        assert "🦝" in captured.out
        assert "hello" in captured.out
        assert "world" in captured.out

    def test_brand_panel_rich_path_does_not_raise(self):
        # Just exercise the Rich path so it's covered.
        ui_kit.brand_panel("smoke", body="ok")

    def test_banner_line_includes_emoji(self, capsys):
        ui_kit.banner_line("hello world")
        captured = capsys.readouterr()
        assert "🦝" in captured.out
        assert "hello world" in captured.out


# ---------------------------------------------------------------------------
# Non-interactive fallback (the path pytest itself takes)
# ---------------------------------------------------------------------------


class TestSelectFallback:
    def test_numeric_index(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO("2\n"))
        result = ui_kit.select(
            "pick one", ["alpha", "beta", "gamma"]
        )
        assert result == "beta"

    def test_default_on_empty_line(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
        result = ui_kit.select(
            "pick", ["a", "b", "c"], default="b"
        )
        assert result == "b"

    def test_value_match_by_name(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO("gamma\n"))
        result = ui_kit.select("pick", ["alpha", "beta", "gamma"])
        assert result == "gamma"

    def test_dict_choices_resolve_to_value(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO("1\n"))
        result = ui_kit.select(
            "pick",
            [{"name": "First option", "value": "first"},
             {"name": "Second", "value": "second"}],
        )
        assert result == "first"

    def test_invalid_then_valid(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO("99\nbeta\n"))
        result = ui_kit.select("pick", ["alpha", "beta"])
        assert result == "beta"


class TestFuzzySelectFallback:
    def test_falls_back_to_select(self, monkeypatch):
        # Same fallback as plain select when InquirerPy or TTY missing.
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO("2\n"))
        result = ui_kit.fuzzy_select(
            "pick", ["alpha", "beta", "gamma"]
        )
        assert result == "beta"


class TestPasswordFallback:
    def test_silent_fallback_uses_getpass(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)

        seen_label: dict[str, str] = {}

        def fake_getpass(label):
            seen_label["label"] = label
            return "sk-test-1234"

        monkeypatch.setattr("getpass.getpass", fake_getpass)
        result = ui_kit.password("Enter your key")
        assert result == "sk-test-1234"
        # The fallback annotates the label so the operator can see they
        # are NOT in the masked path — truthfulness rule.
        assert "non-interactive" in seen_label["label"]

    def test_empty_value_rejected_when_required(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)

        responses = iter(["", "real-key"])
        monkeypatch.setattr("getpass.getpass", lambda _label: next(responses))
        result = ui_kit.password("k", allow_empty=False)
        assert result == "real-key"


class TestConfirmFallback:
    @pytest.mark.parametrize(
        "answer,expected",
        [("y\n", True), ("yes\n", True), ("n\n", False), ("no\n", False)],
    )
    def test_y_n(self, monkeypatch, answer, expected):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO(answer))
        assert ui_kit.confirm("ok?", default=False) is expected

    def test_default_on_empty(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
        assert ui_kit.confirm("ok?", default=True) is True


class TestTextFallback:
    def test_default_on_empty(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
        result = ui_kit.text("name", default="anonymous")
        assert result == "anonymous"

    def test_returns_typed_value(self, monkeypatch):
        monkeypatch.setattr(ui_kit, "_INQUIRER_AVAILABLE", False)
        monkeypatch.setattr(sys, "stdin", io.StringIO("Mahmoud\n"))
        result = ui_kit.text("name", default="anonymous")
        assert result == "Mahmoud"


# ---------------------------------------------------------------------------
# TTY hint
# ---------------------------------------------------------------------------


class TestTTYHint:
    def test_no_op_when_interactive(self, monkeypatch, capsys):
        monkeypatch.setattr(ui_kit, "_is_interactive", lambda: True)
        ui_kit.warn_non_interactive_setup_hint()
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_prints_ssh_t_hint_when_non_tty(self, monkeypatch, capsys):
        monkeypatch.setattr(ui_kit, "_is_interactive", lambda: False)
        ui_kit.warn_non_interactive_setup_hint()
        captured = capsys.readouterr()
        # Either Rich path (with [cyan]🦝[/]) or plain — both must mention
        # the ssh -t invocation truthfully.
        assert "ssh -t" in captured.out
        assert "🦝" in captured.out
