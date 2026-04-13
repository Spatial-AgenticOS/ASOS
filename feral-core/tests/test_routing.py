"""Tests for the Gateway Routing resolver."""

import pytest

from gateway.routing import RouteKey, ResolvedRoute, RouteResolver, RoutingMode


@pytest.fixture
def resolver():
    return RouteResolver()


class TestSingleAgentMode:
    def test_default_mode_is_single(self, resolver: RouteResolver):
        assert resolver.mode is RoutingMode.SINGLE

    def test_all_keys_resolve_to_orchestrator(self, resolver: RouteResolver):
        keys = [
            RouteKey(channel="ws", sender_id="alice"),
            RouteKey(channel="rest", sender_id="bob", group_id="team-1"),
            RouteKey(channel="sms", session_id="sess-99"),
        ]
        for key in keys:
            route = resolver.resolve(key)
            assert route.agent_id == "orchestrator"
            assert route.channel == key.channel

    def test_session_key_is_deterministic(self, resolver: RouteResolver):
        key = RouteKey(channel="ws", sender_id="alice", session_id="s1")
        a = resolver.resolve(key)
        b = resolver.resolve(key)
        assert a.session_key == b.session_key

    def test_session_key_differs_by_sender(self, resolver: RouteResolver):
        k1 = RouteKey(channel="ws", sender_id="alice")
        k2 = RouteKey(channel="ws", sender_id="bob")
        assert resolver.resolve(k1).session_key != resolver.resolve(k2).session_key


class TestMultiAgentMode:
    def test_switch_to_multi(self, resolver: RouteResolver):
        resolver.set_mode(RoutingMode.MULTI)
        assert resolver.mode is RoutingMode.MULTI

    def test_rule_matches(self, resolver: RouteResolver):
        resolver.set_mode(RoutingMode.MULTI)
        resolver.add_rule(
            predicate=lambda k: k.channel == "sms",
            agent_id="sms-agent",
        )
        route = resolver.resolve(RouteKey(channel="sms", sender_id="x"))
        assert route.agent_id == "sms-agent"

    def test_fallback_to_default(self, resolver: RouteResolver):
        resolver.set_mode(RoutingMode.MULTI)
        resolver.add_rule(
            predicate=lambda k: k.channel == "sms",
            agent_id="sms-agent",
        )
        route = resolver.resolve(RouteKey(channel="ws", sender_id="y"))
        assert route.agent_id == "orchestrator"

    def test_priority_ordering(self, resolver: RouteResolver):
        resolver.set_mode(RoutingMode.MULTI)
        resolver.add_rule(
            predicate=lambda k: k.channel == "ws",
            agent_id="low-priority",
            priority=1,
        )
        resolver.add_rule(
            predicate=lambda k: k.channel == "ws" and k.sender_id == "vip",
            agent_id="vip-agent",
            priority=10,
        )
        route = resolver.resolve(RouteKey(channel="ws", sender_id="vip"))
        assert route.agent_id == "vip-agent"

    def test_clear_rules(self, resolver: RouteResolver):
        resolver.set_mode(RoutingMode.MULTI)
        resolver.add_rule(lambda k: True, "custom")
        resolver.clear_rules()
        route = resolver.resolve(RouteKey(channel="ws"))
        assert route.agent_id == "orchestrator"


class TestCustomDefault:
    def test_custom_default_agent(self):
        resolver = RouteResolver(default_agent="my-agent")
        route = resolver.resolve(RouteKey(channel="ws"))
        assert route.agent_id == "my-agent"


class TestSessionKeyStructure:
    def test_includes_group(self, resolver: RouteResolver):
        key = RouteKey(channel="ws", group_id="grp")
        route = resolver.resolve(key)
        assert "g:grp" in route.session_key

    def test_includes_sender(self, resolver: RouteResolver):
        key = RouteKey(channel="ws", sender_id="alice")
        route = resolver.resolve(key)
        assert "u:alice" in route.session_key

    def test_includes_session(self, resolver: RouteResolver):
        key = RouteKey(channel="ws", session_id="s42")
        route = resolver.resolve(key)
        assert "s:s42" in route.session_key

    def test_includes_agent(self, resolver: RouteResolver):
        key = RouteKey(channel="ws")
        route = resolver.resolve(key)
        assert "a:orchestrator" in route.session_key
