"""FERAL v2 ambient-OS client bundle.

This package exists solely so setuptools discovers the directory via
`find_packages(include=["webui_v2*"])` and bundles its static assets
(index.html + assets/*) into the distributed wheel.

The Brain serves these files at `/` (default UI) and `/v2/` (alias) via
StaticFiles mounts configured in feral-core/api/server.py.
"""
