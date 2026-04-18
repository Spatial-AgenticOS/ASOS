"""Smoke test: the generated daemon must import and instantiate without
actually opening a WebSocket. Catches most templating and dependency bugs.
"""

from __future__ import annotations


def test_daemon_importable_and_instantiable():
    from {{cookiecutter.node_id}} import daemon  # type: ignore[import-not-found]

    node = daemon.build_node()
    assert node.node_id == "{{cookiecutter.node_id}}"
    assert node.name == "{{cookiecutter.name}}"
    assert len(daemon.CAPABILITIES) >= 0
    assert "ping" in node._action_handlers  # noqa: SLF001
    assert "demo_actuator" in node._action_handlers  # noqa: SLF001
