"""First-party persona manifests (JSON).

This is a data-only package — every `*.json` here is a `PersonaManifest`
loaded at brain boot via `agents.persona_loader.load_personas`. Marked
as a real package (`__init__.py` present) so `setuptools.package-data`
in `pyproject.toml` ships the JSONs in the wheel. Without this marker
the wheel installed via `pip install feral-ai` was missing every
manifest, and the brain logged
`Persona directory not found: <site-packages>/agents/personas (skipping)`
on every boot. Source: audit-r9 brief #08.
"""
