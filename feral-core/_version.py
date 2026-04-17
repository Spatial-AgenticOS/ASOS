"""Single source of truth for FERAL version.

Read by pyproject.toml (attr) and imported by CLI/API modules.

If for any reason this module is importable but the literal below gets
out of sync with the installed package metadata, we prefer metadata.
This also lets downstream callers survive even weirder packaging edge
cases.
"""

__version__ = "2026.4.16"

try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version
    try:
        __version__ = _pkg_version("feral-ai")
    except PackageNotFoundError:
        pass
except Exception:
    pass
