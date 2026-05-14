"""Phase 5 (audit-r10 overhaul) — runtime capability registry.

Tracks which structured `phone.*` / `glasses.*` action names are
currently routable, based on the skill manifests connected nodes
publish in `node_register.skills` (the Phase 4 wire field).

Two readers consume this:

* `GET /api/capabilities` — the REST surface that returns the union
  of brain-host skills + connected-node skills. Web + iOS clients
  read this to render a "what can this brain do right now" pane and
  (Phase 6) the permission-card flow.

* Orchestrator routing — when the planner emits an action like
  `phone.call.start`, it queries `find_handler("phone.call.start")`
  to decide whether to dispatch (returns a handler) vs short-circuit
  to a "no iPhone connected" answer (returns None).

Brain-host (Mac-side) skills are tracked by `SkillRegistry` already
and are NOT re-mirrored here — the API endpoint merges them at
response time. CapabilityRegistry is exclusively the NODE catalog.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Optional


@dataclass(frozen=True)
class CapabilityHandler:
    """Where an action can be executed right now.

    `surface` matches the execution-surface vocabulary in
    `security.dangerous_tools` so Phase 1's policy stays the single
    source of truth — `find_handler(...).surface` is the value the
    orchestrator passes into `resolve_surface_from_context`.
    """

    surface: str
    node_id: Optional[str]
    node_type: str
    platform: str


def _surface_for_node_type(node_type: str) -> str:
    """Map HUP `node_type` → dangerous_tools execution surface.

    Phase 1 introduced `brain_host` (Mac) and `phone_actuator` (iOS
    skills). Phase 5 keeps the mapping conservative — glasses /
    wearables / cameras fall under a generic `node_actuator` bucket
    that the existing policy treats as the equivalent of the BLE
    adapter surface (no Mac tool execution allowed). Phase 11 adds
    the desktop_control half of `brain_host` and may want to split
    `glasses_actuator` out further; this helper is the seam.
    """
    nt = (node_type or "").lower()
    if nt in ("phone", "tablet"):
        return "phone_actuator"
    if nt in ("glasses",):
        return "glasses_actuator"
    if nt in ("desktop", "server", "rpi"):
        return "brain_host"
    return "node_actuator"


class CapabilityRegistry:
    """Live catalog of node-published skill manifests."""

    def __init__(self) -> None:
        self._lock = RLock()
        # node_id → {"node_type", "platform", "skills": list[dict]}
        # where each skill dict matches the Phase 4 SkillManifest
        # wire shape: {id, name, description, actions: [...]}.
        self._nodes: dict[str, dict] = {}

    # ── Lifecycle ────────────────────────────────────────────────

    def register_node(
        self,
        node_id: str,
        *,
        node_type: str,
        platform: str,
        skills: list[dict] | None,
    ) -> None:
        """Replace any prior record for `node_id`. Called from the
        `node_register` handler in `api/server.py`.
        """
        with self._lock:
            self._nodes[node_id] = {
                "node_type": (node_type or "").lower(),
                "platform": (platform or "").lower(),
                "skills": list(skills or []),
            }

    def unregister_node(self, node_id: str) -> None:
        """Called from the `node_bye` handler and from the
        `WebSocketDisconnect` cleanup in `api/server.py`.
        """
        with self._lock:
            self._nodes.pop(node_id, None)

    # ── Query ────────────────────────────────────────────────────

    def find_handler(self, action_name: str) -> Optional[CapabilityHandler]:
        """Return the first connected node that publishes `action_name`,
        or `None` when no node currently advertises it.

        First-match semantics are fine while at most one phone /
        glasses / wearable of each kind is connected at a time, which
        is the operator's actual deployment. Multi-phone routing is
        a Phase 12+ concern.
        """
        if not action_name:
            return None
        with self._lock:
            for node_id, info in self._nodes.items():
                for skill in info["skills"]:
                    for action in skill.get("actions", []) or []:
                        if action.get("name") == action_name:
                            return CapabilityHandler(
                                surface=_surface_for_node_type(info["node_type"]),
                                node_id=node_id,
                                node_type=info["node_type"],
                                platform=info["platform"],
                            )
        return None

    def connected_node_ids(self) -> list[str]:
        with self._lock:
            return list(self._nodes.keys())

    def has_node_type(self, node_type: str) -> bool:
        """True if any currently-connected node has `node_type`.
        Used by the orchestrator to disambiguate "do I have a phone"
        without enumerating skills."""
        target = (node_type or "").lower()
        if not target:
            return False
        with self._lock:
            return any(info["node_type"] == target for info in self._nodes.values())

    def snapshot_nodes(self) -> list[dict]:
        """Wire format for `GET /api/capabilities` (nodes section).

        Returns a deep-enough copy that the API handler can serialize
        it directly without callers worrying about concurrent
        mutation under the registry lock.
        """
        with self._lock:
            return [
                {
                    "node_id": node_id,
                    "node_type": info["node_type"],
                    "platform": info["platform"],
                    "surface": _surface_for_node_type(info["node_type"]),
                    "skills": [dict(skill) for skill in info["skills"]],
                }
                for node_id, info in self._nodes.items()
            ]
