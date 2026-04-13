"""
FERAL Gateway Routing — Resolve Incoming Messages to Agent Sessions
====================================================================
Maps (channel, sender, session, group) tuples to the correct agent
and session key.  Inspired by OpenClaw's resolve-route pattern.

Default mode: single-agent — every message routes to the main
orchestrator.  Multi-agent mode assigns per-channel or per-sender
agents when enabled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("feral.gateway.routing")


class RoutingMode(Enum):
    SINGLE = "single"
    MULTI = "multi"


@dataclass(frozen=True)
class RouteKey:
    """Identifies the origin of an incoming message."""

    channel: str
    sender_id: str = ""
    session_id: str = ""
    group_id: str = ""


@dataclass(frozen=True)
class ResolvedRoute:
    """Where a message should be delivered."""

    agent_id: str
    session_key: str
    channel: str


RoutePredicate = Callable[[RouteKey], bool]


@dataclass
class _RouteRule:
    predicate: RoutePredicate
    agent_id: str
    priority: int = 0


class RouteResolver:
    """
    Resolve an incoming RouteKey to a ResolvedRoute.

    In single-agent mode every key maps to the main orchestrator.
    In multi-agent mode, registered rules are evaluated in priority
    order; the first matching rule wins.
    """

    DEFAULT_AGENT = "orchestrator"

    def __init__(
        self,
        mode: RoutingMode = RoutingMode.SINGLE,
        default_agent: str = DEFAULT_AGENT,
    ):
        self._mode = mode
        self._default_agent = default_agent
        self._rules: list[_RouteRule] = []

    @property
    def mode(self) -> RoutingMode:
        return self._mode

    def set_mode(self, mode: RoutingMode) -> None:
        self._mode = mode
        logger.info("Routing mode changed to %s", mode.value)

    def add_rule(
        self,
        predicate: RoutePredicate,
        agent_id: str,
        priority: int = 0,
    ) -> None:
        """Register a routing rule (multi-agent mode only)."""
        self._rules.append(_RouteRule(predicate, agent_id, priority))
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def clear_rules(self) -> None:
        self._rules.clear()

    def resolve(self, key: RouteKey) -> ResolvedRoute:
        """Resolve a RouteKey to a ResolvedRoute."""
        agent_id = self._resolve_agent(key)
        session_key = self._build_session_key(key, agent_id)
        return ResolvedRoute(
            agent_id=agent_id,
            session_key=session_key,
            channel=key.channel,
        )

    def _resolve_agent(self, key: RouteKey) -> str:
        if self._mode is RoutingMode.SINGLE:
            return self._default_agent

        for rule in self._rules:
            if rule.predicate(key):
                logger.debug(
                    "Rule matched: agent=%s for key=%s",
                    rule.agent_id,
                    key,
                )
                return rule.agent_id

        return self._default_agent

    @staticmethod
    def _build_session_key(key: RouteKey, agent_id: str) -> str:
        """
        Deterministic session key so the same sender on the same channel
        always resumes the same conversation with a given agent.
        """
        parts = [key.channel]
        if key.group_id:
            parts.append(f"g:{key.group_id}")
        if key.sender_id:
            parts.append(f"u:{key.sender_id}")
        if key.session_id:
            parts.append(f"s:{key.session_id}")
        parts.append(f"a:{agent_id}")
        return ":".join(parts)
