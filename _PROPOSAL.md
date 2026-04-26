# W24c — Scrub "openclaw" from shipped artifacts (v2)

One mechanical pass: rewrite every non-exempt occurrence of "openclaw"
(case-insensitive) in shipped artifacts per the workspace rule's replacement
vocabulary, then add a CI linter + pytest that permanently blocks the string
from returning. Rewrites are prose-only (comments, docstrings, string
literals, markdown body text); rename a test function and a couple of
internal identifiers where the name itself cites the reference project. No
runtime behaviour changes.

## Hit list (from the prescribed rg enumeration)

### Docs
- SECURITY.md
- TRACK_A_CHANNELS_PROVIDERS.md
- docs/contributing-channels.md

### feral-core/security/auth_profiles
- __init__.py
- external_auth.py
- migrate.py
- oauth_refresh_lock.py
- paths.py
- store.py
- types.py
- usage.py

### feral-core/process/supervisor
- __init__.py (pkg)
- supervisor.py
- registry.py
- adapters/__init__.py
- adapters/child.py
- adapters/pty.py
- ../__init__.py (feral-core/process/__init__.py)

### feral-core/agents + api
- agents/orchestrator.py
- agents/subagent_spawner.py
- api/routes/sessions.py

### feral-core/channels
- manifest.py
- manifest_schema.json

### feral-core/tests
- test_subagent_allowlist.py
- test_subagent_lifecycle.py
- test_subagent_model_override.py
- test_subagent_scope.py
- test_subagent_steer_failure_clears_suppression.py
- test_process_supervisor_no_output_timeout.py
- test_process_supervisor_overall_timeout.py
- test_process_supervisor_pty_login_shell.py
- test_process_supervisor_registry_finalize.py
- test_process_supervisor_scope_cancel.py
- test_auth_profiles_multi_agent.py
- test_auth_profiles_oauth_refresh_lock.py
- security/test_mcp_approval_bypass.py
- security/test_executor_approval_bypass.py
- security/test_twin_approval_bypass.py
- security/test_pairing_approval_bypass.py

### New files
- scripts/check_no_third_party_names.py
- .github/workflows/no-third-party-names-lint.yml
- feral-core/tests/test_no_third_party_names_literal.py
