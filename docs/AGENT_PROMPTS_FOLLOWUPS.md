# Agent prompt follow-ups

One-line notes from workstreams when a deliverable required touching a
file outside the workstream's owned-paths list. Conductor sweeps this
file periodically.

- W12 added `pytest_addoption(--runsoak)` + `pytest_collection_modifyitems` soak-skip hook to `feral-core/tests/conftest.py` (no prior `pytest_addoption` existed); needed to gate the soak suite.
- W12 registered the `soak` marker in `feral-core/pyproject.toml` `[tool.pytest.ini_options].markers`; needed so `@pytest.mark.soak` does not raise `PytestUnknownMarkWarning` under strict markers.
- W12 created `docs/mintlify/operations/` (new sub-tree) and `docs/mintlify/operations/soak.mdx`; flag if the mintlify nav owner wants a different home.
