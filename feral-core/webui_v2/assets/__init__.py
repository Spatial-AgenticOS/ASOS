"""Static assets subpackage for the v2 ambient-OS bundle.

Mirrors the pattern used by webui.assets — the `__init__.py` makes this
a setuptools-discoverable subpackage so `[tool.setuptools.package-data]`
can target `webui_v2.assets` for the .js / .css / .map files vite emits.
"""
