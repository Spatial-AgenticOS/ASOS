"""Offline tests for `feral app` CLI — init, validate, build.

`install` + `publish` require a running brain / registry respectively
so we smoke them as process-level integration tests elsewhere.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

from cli import app_commands


def test_slugify_produces_dns_safe_slug():
    assert app_commands._slugify("My Cool App!") == "my-cool-app"
    assert app_commands._slugify("  1stApp ") == "stapp"
    assert app_commands._slugify("---") == ""
    assert app_commands._slugify("FERAL.AI.Messenger") == "feralaimessenger"


def test_init_scaffolds_expected_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app_commands.cmd_app_init("Demo Messenger")
    scaffolded = tmp_path / "demo-messenger"
    assert scaffolded.is_dir()
    assert (scaffolded / "manifest.yaml").is_file()
    assert (scaffolded / "README.md").is_file()
    assert (scaffolded / ".feralignore").is_file()


def test_init_rejects_existing_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "demo-app").mkdir()
    with pytest.raises(SystemExit):
        app_commands.cmd_app_init("demo-app")


def test_validate_accepts_scaffolded_app(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    app_commands.cmd_app_init("Demo Messenger")
    app_commands.cmd_app_validate(str(tmp_path / "demo-messenger"))
    out = capsys.readouterr().out
    assert "OK." in out
    assert "demo-messenger" in out


def test_validate_rejects_broken_manifest(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text('{"app_id": "nope"}')
    with pytest.raises(SystemExit):
        app_commands.cmd_app_validate(str(bad))


def test_validate_rejects_missing_dir(tmp_path):
    with pytest.raises(SystemExit):
        app_commands.cmd_app_validate(str(tmp_path / "ghost"))


def test_build_produces_tarball(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app_commands.cmd_app_init("Demo Messenger")
    src = tmp_path / "demo-messenger"
    out_path = tmp_path / "demo-messenger.tar.gz"
    app_commands.cmd_app_build(str(src), out=str(out_path))
    assert out_path.exists() and out_path.stat().st_size > 0


def test_feralignore_excludes_dist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app_commands.cmd_app_init("Demo Messenger")
    src = tmp_path / "demo-messenger"
    # Pre-create a dist folder w/ a file. .feralignore already excludes dist/
    # so the tarball should not contain it.
    (src / "dist").mkdir()
    (src / "dist" / "stale.bin").write_text("stale")
    out_path = tmp_path / "out.tar.gz"
    app_commands.cmd_app_build(str(src), out=str(out_path))
    import tarfile
    with tarfile.open(out_path, "r:gz") as tar:
        names = tar.getnames()
    assert not any(n.startswith("dist/") for n in names)


def test_load_manifest_inlines_template_ref(tmp_path):
    import json
    src = tmp_path / "app"
    src.mkdir()
    (src / "surfaces").mkdir()
    (src / "surfaces" / "home.sdui.json").write_text(
        json.dumps({"type": "Text", "value": "hi"})
    )
    (src / "manifest.json").write_text(json.dumps({
        "app_id": "x",
        "surfaces": [
            {"surface_id": "home", "template_root": "surfaces/home.sdui.json"},
        ],
        "entry_surface_id": "home",
    }))
    raw = app_commands._load_manifest(src)
    assert raw["surfaces"][0]["template_root"] == {"type": "Text", "value": "hi"}
