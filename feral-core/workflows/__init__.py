"""First-party workflow-pack manifests (JSON).

Data-only package. Each `*.json` is a `WorkflowPackManifest` loaded at
brain boot via `agents.persona_loader.load_workflow_packs`. Marked as
a real package so `setuptools.package-data` ships the JSONs in the
wheel — without this, `pip install feral-ai` users saw
`Workflow-pack directory not found: <site-packages>/workflows (skipping)`
on every boot. Source: audit-r9 brief #08.
"""
