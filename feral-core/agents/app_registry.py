"""AppRegistry — SQLite-backed index of installed third-party GenUI apps.

Keeps one row per installed app + an on-disk directory under
``~/.feral/apps/<app_id>/`` holding the manifest and any static
bundle assets (logos, pre-rendered surface defaults, readmes).

Install sources
---------------
1. **Local directory** — ``install_from_dir(path)``. The directory must
   contain a ``manifest.yaml`` or ``manifest.json`` that parses into an
   :class:`models.app_manifest.AppManifest`. Assets are copied, not
   referenced, so a subsequent edit in the source tree doesn't change
   the installed surface.
2. **Registry download** — ``install_from_registry(item_id)``.
   Delegates to the existing ``MarketplaceClient`` tarball download
   path and then calls :meth:`install_from_dir` on the unpacked
   content. See Commit 6 for the CLI-side publish path.

Data lifecycle
--------------
The registry never holds live data for an app. It exposes
:meth:`open_surface` which:

1. Looks up the surface spec in the stored manifest.
2. Asks the :class:`HybridGenerator` to render it with whatever data
   binding the caller provides.
3. Returns a plain SDUI tree ready to ship over the ``sdui`` wire
   message.

Every action dispatched from the rendered surface must flow through
:meth:`handle_app_action`, which validates the action against the
surface's declared contract before invoking the orchestrator. That
contract + per-user cache are the two invariants Commit 4 relies on.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from models.app_manifest import ActionSpec, AppManifest, SurfaceSpec

logger = logging.getLogger("feral.app_registry")


DEFAULT_APPS_DIR_NAME = "apps"
DEFAULT_APPS_DB_NAME = "apps.db"


@dataclass
class InstalledApp:
    app_id: str
    version: str
    manifest: AppManifest
    install_dir: Path
    installed_at: float


class AppRegistryError(RuntimeError):
    """Raised when install/open fails in a way the caller should see."""


class AppRegistry:
    """SQLite-backed store of installed FERAL GenUI apps."""

    _DDL = """
    CREATE TABLE IF NOT EXISTS installed_apps (
        app_id        TEXT PRIMARY KEY,
        version       TEXT NOT NULL,
        manifest_json TEXT NOT NULL,
        install_dir   TEXT NOT NULL,
        installed_at  REAL NOT NULL
    );
    """

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        apps_dir: str | Path | None = None,
        hybrid_generator: Optional["HybridGenerator"] = None,
    ):
        self._db_path = str(db_path) if db_path else ":memory:"
        self._apps_dir = Path(apps_dir) if apps_dir else Path("/tmp/feral-apps-mem")
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._apps_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._DDL)
        self._hybrid: Optional[HybridGenerator] = hybrid_generator

    @property
    def apps_dir(self) -> Path:
        return self._apps_dir

    def set_hybrid_generator(self, hybrid: "HybridGenerator") -> None:
        self._hybrid = hybrid

    # ------------------------------------------------------------------
    # Install / uninstall
    # ------------------------------------------------------------------

    def install_from_dir(self, source_dir: str | Path, *, overwrite: bool = True) -> InstalledApp:
        """Install an app from a local directory containing a manifest + assets.

        Copies everything under *source_dir* into
        ``<apps_dir>/<app_id>/`` so a later edit to the source tree
        doesn't mutate the installed bundle.
        """
        source = Path(source_dir).expanduser().resolve()
        if not source.is_dir():
            raise AppRegistryError(f"not a directory: {source}")
        manifest = _load_manifest_from_dir(source)
        app_id = manifest.app_id

        existing = self.get(app_id)
        if existing and not overwrite:
            raise AppRegistryError(f"app {app_id!r} already installed")

        dest = self._apps_dir / app_id
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        _copy_tree(source, dest)

        now = time.time()
        manifest_blob = manifest.model_dump_json()
        self._conn.execute(
            """INSERT INTO installed_apps
                (app_id, version, manifest_json, install_dir, installed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(app_id) DO UPDATE SET
                    version       = excluded.version,
                    manifest_json = excluded.manifest_json,
                    install_dir   = excluded.install_dir,
                    installed_at  = excluded.installed_at""",
            (app_id, manifest.version, manifest_blob, str(dest), now),
        )
        self._conn.commit()
        logger.info("Installed app %s@%s at %s", app_id, manifest.version, dest)
        return InstalledApp(
            app_id=app_id,
            version=manifest.version,
            manifest=manifest,
            install_dir=dest,
            installed_at=now,
        )

    def uninstall(self, app_id: str, *, purge_cache: bool = True) -> bool:
        existing = self.get(app_id)
        if existing is None:
            return False
        if existing.install_dir.exists():
            shutil.rmtree(existing.install_dir, ignore_errors=True)
        self._conn.execute("DELETE FROM installed_apps WHERE app_id = ?", (app_id,))
        self._conn.commit()
        if purge_cache and self._hybrid is not None:
            try:
                self._hybrid.purge_app_cache(app_id)
            except Exception as exc:
                logger.debug("purge_app_cache failed: %s", exc)
        return True

    def list(self) -> list[InstalledApp]:
        rows = self._conn.execute(
            "SELECT * FROM installed_apps ORDER BY installed_at DESC"
        ).fetchall()
        return [self._row_to_installed(r) for r in rows]

    def get(self, app_id: str) -> Optional[InstalledApp]:
        row = self._conn.execute(
            "SELECT * FROM installed_apps WHERE app_id = ?", (app_id,)
        ).fetchone()
        return self._row_to_installed(row) if row else None

    # ------------------------------------------------------------------
    # Surface access
    # ------------------------------------------------------------------

    async def open_surface(
        self,
        app_id: str,
        surface_id: str,
        *,
        session_id: str = "",
        data: Optional[dict] = None,
        user_fingerprint: str = "default",
        regenerate: bool = False,
    ) -> dict:
        """Return a ready-to-render SDUI tree for *surface_id*."""
        app = self.get(app_id)
        if app is None:
            raise AppRegistryError(f"app {app_id!r} not installed")
        surface = app.manifest.get_surface(surface_id)
        if surface is None:
            raise AppRegistryError(
                f"surface {surface_id!r} not declared on app {app_id!r}"
            )
        if self._hybrid is None:
            raise AppRegistryError("HybridGenerator not configured")
        tree = await self._hybrid.render(
            app_id=app_id,
            manifest=app.manifest,
            surface=surface,
            data=data or {},
            user_fingerprint=user_fingerprint,
            regenerate=regenerate,
            bundle_dir=app.install_dir,
        )
        return {
            "app_id": app_id,
            "surface_id": surface_id,
            "screen_id": f"{app_id}:{surface_id}:{session_id or user_fingerprint}",
            "root": tree,
        }

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def validate_action(
        self,
        app_id: str,
        surface_id: str,
        action_id: str,
        value: Any = None,
    ) -> ActionSpec:
        """Raise if action_id isn't in the surface's contract; otherwise
        return the matching spec.

        Used by :func:`feral-core/agents/ui_handlers.handle_ui_event`
        and by the /api/apps dispatch path.
        """
        app = self.get(app_id)
        if app is None:
            raise AppRegistryError(f"app {app_id!r} not installed")
        surface = app.manifest.get_surface(surface_id)
        if surface is None:
            raise AppRegistryError(
                f"surface {surface_id!r} not declared on app {app_id!r}"
            )
        for action in surface.action_contract:
            if action.action_id == action_id:
                return action
        raise AppRegistryError(
            f"action {action_id!r} is not declared on surface {surface_id!r} "
            f"of app {app_id!r}"
        )

    def resolve_app_and_surface(
        self, screen_id: str
    ) -> Optional[tuple[str, str]]:
        """Parse an app-scoped ``screen_id`` back into (app_id, surface_id)."""
        if not screen_id or ":" not in screen_id:
            return None
        parts = screen_id.split(":")
        if len(parts) < 2:
            return None
        return parts[0], parts[1]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_installed(row: sqlite3.Row) -> InstalledApp:
        manifest_data = json.loads(row["manifest_json"])
        manifest = AppManifest(**manifest_data)
        return InstalledApp(
            app_id=row["app_id"],
            version=row["version"],
            manifest=manifest,
            install_dir=Path(row["install_dir"]),
            installed_at=row["installed_at"],
        )


# ----------------------------------------------------------------------
# Filesystem helpers
# ----------------------------------------------------------------------


def _load_manifest_from_dir(source: Path) -> AppManifest:
    """Parse the manifest from `source/manifest.yaml` or `manifest.json`."""
    yaml_path = source / "manifest.yaml"
    json_path = source / "manifest.json"
    if yaml_path.exists():
        try:
            import yaml
        except ImportError as exc:
            raise AppRegistryError("pyyaml is required to parse manifest.yaml") from exc
        raw = yaml.safe_load(yaml_path.read_text()) or {}
    elif json_path.exists():
        raw = json.loads(json_path.read_text())
    else:
        raise AppRegistryError(
            f"no manifest.yaml or manifest.json found in {source}"
        )
    # Inline `template_root` can live beside the manifest as a
    # separate .sdui.json file; resolve any ``"$ref"`` style shorthand.
    _inline_surface_templates(raw, source)
    try:
        return AppManifest(**raw)
    except ValidationError as exc:
        raise AppRegistryError(f"invalid manifest in {source}: {exc}") from exc


def _inline_surface_templates(raw: dict[str, Any], source: Path) -> None:
    """If a surface's template_root is a relative-path string, load it."""
    surfaces = raw.get("surfaces")
    if not isinstance(surfaces, list):
        return
    for surface in surfaces:
        if not isinstance(surface, dict):
            continue
        template_root = surface.get("template_root")
        if not isinstance(template_root, str):
            continue
        candidate = (source / template_root).resolve()
        if candidate.is_file():
            surface["template_root"] = json.loads(candidate.read_text())


def _copy_tree(src: Path, dst: Path) -> None:
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)


# ----------------------------------------------------------------------
# HybridGenerator
# ----------------------------------------------------------------------


class HybridGenerator:
    """Render a surface by combining authored templates + LLM fallback.

    Flow per ``render()`` call:

    1. **authored** surface → fill ``template_root`` with ``$data.*``
       bindings and return. No LLM.
    2. **generated** surface → look up cached LLM render per
       ``(app_id, surface_id, user_fingerprint, schema_version)``; if
       present, hydrate with data and return. If missing, try the
       publisher-default bundled at ``bundle_dir/surfaces/<surface>.default.json``
       before calling the LLM.
    3. **hybrid** surface → authored template is the default. Only
       regenerates when ``regenerate=True`` (user-customization signal)
       or when the cached personalised render exists.

    The cache directory is structured as::

        <cache_dir>/
            <app_id>/
                <surface_id>/
                    <fingerprint>.v<schema_version>.json
    """

    def __init__(
        self,
        *,
        genui_engine=None,
        cache_dir: str | Path | None = None,
    ):
        self._genui = genui_engine
        self._cache_dir = Path(cache_dir) if cache_dir else Path("/tmp/feral-hybrid-cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def set_genui_engine(self, engine) -> None:
        self._genui = engine

    async def render(
        self,
        *,
        app_id: str,
        manifest: AppManifest,
        surface: SurfaceSpec,
        data: dict,
        user_fingerprint: str = "default",
        regenerate: bool = False,
        bundle_dir: Optional[Path] = None,
    ) -> dict:
        kind = surface.kind

        if kind == "authored":
            assert surface.template_root is not None
            return _hydrate(surface.template_root, data)

        cache_path = self._cache_path_for(
            app_id, surface.surface_id, user_fingerprint, surface.schema_version
        )

        if kind == "generated":
            if not regenerate and cache_path.is_file():
                cached_tree = _safe_read_json(cache_path)
                if cached_tree is not None:
                    return _hydrate(cached_tree, data)
            # Prefer publisher default before we hit the LLM.
            default_tree = _read_publisher_default(bundle_dir, surface.surface_id)
            if default_tree is not None and not regenerate:
                self._write_cache(cache_path, default_tree)
                return _hydrate(default_tree, data)
            generated = await self._llm_generate(manifest, surface, data)
            self._write_cache(cache_path, generated)
            return _hydrate(generated, data)

        if kind == "hybrid":
            assert surface.template_root is not None
            if regenerate:
                # Try the publisher's shipped default first when present.
                # That's the "signed default" path the plan calls out.
                default_tree = _read_publisher_default(bundle_dir, surface.surface_id)
                if default_tree is not None and self._genui is None:
                    self._write_cache(cache_path, default_tree)
                    return _hydrate(default_tree, data)
                generated = await self._llm_generate(manifest, surface, data)
                self._write_cache(cache_path, generated)
                return _hydrate(generated, data)
            if cache_path.is_file():
                cached_tree = _safe_read_json(cache_path)
                if cached_tree is not None:
                    return _hydrate(cached_tree, data)
            return _hydrate(surface.template_root, data)

        # Fallback — should be caught by manifest validator but safe-guard anyway.
        raise AppRegistryError(f"unknown surface kind {kind!r}")

    # --------------------------------------------------------------
    # Cache ops
    # --------------------------------------------------------------

    def purge_app_cache(self, app_id: str) -> int:
        """Remove every cached render for *app_id*. Returns file count."""
        app_dir = self._cache_dir / app_id
        if not app_dir.is_dir():
            return 0
        count = 0
        for surface_dir in app_dir.iterdir():
            if surface_dir.is_dir():
                for f in surface_dir.iterdir():
                    if f.is_file():
                        f.unlink()
                        count += 1
                surface_dir.rmdir()
        try:
            app_dir.rmdir()
        except OSError:
            pass
        return count

    def _cache_path_for(
        self, app_id: str, surface_id: str, fingerprint: str, schema_version: int
    ) -> Path:
        safe_finger = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]
        path = (
            self._cache_dir
            / app_id
            / surface_id
            / f"{safe_finger}.v{schema_version}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _write_cache(self, path: Path, tree: dict) -> None:
        payload = {
            "generated_at": time.time(),
            "tree": tree,
        }
        path.write_text(json.dumps(payload))

    async def _llm_generate(
        self, manifest: AppManifest, surface: SurfaceSpec, data: dict
    ) -> dict:
        """Generate SDUI via the shared GenUIEngine with publisher style."""
        if self._genui is None:
            return _deterministic_fallback(manifest, surface)
        prompt = _build_llm_prompt(manifest, surface, data)
        try:
            tree = await self._genui.generate_from_prompt(
                prompt, context={"brand": manifest.brand.model_dump()}
            )
            if isinstance(tree, dict) and tree.get("type"):
                return tree
        except Exception as exc:
            logger.warning(
                "HybridGenerator LLM call failed for %s/%s: %s — falling back",
                manifest.app_id, surface.surface_id, exc,
            )
        return _deterministic_fallback(manifest, surface)


# ----------------------------------------------------------------------
# Template hydration helpers
# ----------------------------------------------------------------------


def _hydrate(tree: Any, data: dict) -> Any:
    """Walk *tree* and replace ``$data.foo.bar`` strings with data values.

    Strings of the form ``$data.a.b`` (and ``${data.a.b}``) resolve to
    the matching path in ``data``. Lists walk recursively; dicts walk
    every value. Non-string leaves are returned as-is. Missing paths
    render as ``""`` to avoid crashes on optional bindings.
    """
    if isinstance(tree, str):
        return _resolve_placeholder(tree, data)
    if isinstance(tree, list):
        return [_hydrate(item, data) for item in tree]
    if isinstance(tree, dict):
        out = {}
        for key, value in tree.items():
            out[key] = _hydrate(value, data)
        return out
    return tree


def _resolve_placeholder(text: str, data: dict) -> str | Any:
    if not text:
        return text
    stripped = text.strip()
    # Match either `$data.a.b.c` or `${data.a.b.c}`.
    if stripped.startswith("${") and stripped.endswith("}"):
        inner = stripped[2:-1]
    elif stripped.startswith("$"):
        inner = stripped[1:]
    else:
        return text
    if not inner.startswith("data"):
        return text
    parts = inner.split(".")[1:]
    current: Any = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            # Numeric segment indexes into the list (e.g. contacts.0.name).
            try:
                idx = int(part)
            except ValueError:
                return ""
            if 0 <= idx < len(current):
                current = current[idx]
            else:
                return ""
        else:
            return ""
    return current


# ----------------------------------------------------------------------
# Publisher default + LLM prompt + fallback
# ----------------------------------------------------------------------


def _read_publisher_default(bundle_dir: Optional[Path], surface_id: str) -> Optional[dict]:
    if bundle_dir is None:
        return None
    candidate = bundle_dir / "surfaces" / f"{surface_id}.default.json"
    if not candidate.is_file():
        return None
    try:
        data = json.loads(candidate.read_text())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _safe_read_json(path: Path) -> Optional[dict]:
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return None
    if isinstance(raw, dict) and "tree" in raw and isinstance(raw["tree"], dict):
        return raw["tree"]
    return raw if isinstance(raw, dict) else None


def _build_llm_prompt(manifest: AppManifest, surface: SurfaceSpec, data: dict) -> str:
    interactions_chunk = manifest.interactions.to_system_prompt_chunk()
    brand = manifest.brand
    prompt_parts = [
        f"App: {manifest.app_id} (v{manifest.version}).",
        f"Brand: {brand.name}, primary color {brand.primary_color}.",
        "",
        interactions_chunk,
        "",
        f"Generate SDUI for surface '{surface.surface_id}': {surface.description or surface.title}.",
        "",
        f"Generation prompt: {surface.generation_prompt}",
        "",
    ]
    if surface.action_contract:
        prompt_parts.append(
            "Allowed action_ids: "
            + ", ".join(a.action_id for a in surface.action_contract)
        )
    if data:
        prompt_parts.append(f"Render with this data: {json.dumps(data)[:1000]}")
    return "\n".join(prompt_parts)


def _deterministic_fallback(manifest: AppManifest, surface: SurfaceSpec) -> dict:
    """Non-LLM fallback so the UI is never empty when the VLM is unavailable.

    Renders a simple Card with the app brand + a note that the agent
    couldn't generate the surface. Matches the "never fake" contract —
    it's honest, not pretending to be a real surface.
    """
    return {
        "type": "Card",
        "children": [
            {"type": "Text", "value": manifest.brand.name, "style": "headline", "color": manifest.brand.primary_color},
            {"type": "Divider"},
            {"type": "Text", "value": f"{surface.title or surface.surface_id}", "style": "subtitle"},
            {
                "type": "Text",
                "value": (
                    "The agent couldn't generate this surface right now. "
                    "Please open the app's main screen or try again in a moment."
                ),
                "style": "body",
            },
        ],
    }


# ----------------------------------------------------------------------
# Default on-disk paths
# ----------------------------------------------------------------------


def default_apps_db_path() -> str:
    from config.loader import feral_home

    return str(feral_home() / DEFAULT_APPS_DB_NAME)


def default_apps_dir() -> Path:
    from config.loader import feral_home

    return feral_home() / DEFAULT_APPS_DIR_NAME


def default_hybrid_cache_dir() -> Path:
    from config.loader import feral_home

    return feral_home() / ".cache" / "hybrid_genui"
