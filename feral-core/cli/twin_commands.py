"""``feral twin …`` CLI — REST-wrapped helpers for per-domain twin policies
and the approval queue."""

from __future__ import annotations

import json
import sys

from cli.main import _http_get, _http_post, _http_delete  # type: ignore  # noqa


def _mode_from_flags(args) -> str:
    if getattr(args, "twin_mode_disabled", False):
        return "disabled"
    if getattr(args, "twin_mode_auto", False):
        return "auto_send"
    # default + explicit --draft-only both land here
    return "draft_only"


def cmd_twin(args) -> None:
    action = getattr(args, "action", None) or ""
    if action == "grant":
        payload = {
            "domain": args.domain,
            "mode": _mode_from_flags(args),
            "time_windows": list(getattr(args, "twin_windows", []) or []),
            "max_per_day": int(getattr(args, "max_per_day", 10)),
            "requires_user_online": bool(getattr(args, "requires_user_online", False)),
        }
        resp = _http_post("/api/twin/policies", payload)
        if resp.get("success"):
            print(f"twin policy set for {payload['domain']} (mode={payload['mode']})")
        else:
            print(f"error: {resp}", file=sys.stderr)
            sys.exit(1)
        return

    if action == "list":
        data = _http_get("/api/twin/policies") or {}
        policies = data.get("policies") or []
        if not policies:
            print("no twin policies configured")
            return
        for p in policies:
            windows = ",".join(p.get("time_windows") or []) or "anytime"
            print(f"- {p['domain']:22s} mode={p['mode']:11s} cap/day={p['max_per_day']} windows={windows}")
        return

    if action == "revoke":
        resp = _http_delete(f"/api/twin/policies/{args.domain}")
        if resp.get("success"):
            print(f"revoked {args.domain}")
        else:
            print(f"error: {resp}", file=sys.stderr)
            sys.exit(1)
        return

    if action == "pending":
        data = _http_get("/api/twin/approvals?status=pending") or {}
        pending = data.get("approvals") or []
        if not pending:
            print("no pending twin approvals")
            return
        for row in pending:
            ctx = json.dumps(row.get("context") or {})[:120]
            print(f"- {row['approval_id'][:8]}… {row['domain']}/{row['action']}  {ctx}")
        return

    print("usage: feral twin {grant DOMAIN | list | revoke DOMAIN | pending}")
    sys.exit(2)
