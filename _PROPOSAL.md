# W24b — kill plaintext credentials.json leak

**Bug.** `v2026.5.0` ships a P0 regression:
`ConfigLoader.save_credentials` (`feral-core/config/loader.py:340-348`)
writes `~/.feral/credentials.json` in plaintext on every save, alongside
the W9 encrypted vault — exactly the live-log line
`[feral.config] Credentials saved to .../credentials.json`.

**Surgery (ONE function).** Rewrite `ConfigLoader.save_credentials` to:
(a) keep updating the in-memory `self._credentials` dict so boot-time env
export keeps working, (b) route each flat `(key, value)` string credential
into `BlindVault.set_credential` (lazily constructed, honours `FERAL_HOME`
via `feral_home()`), (c) NEVER touch `credentials.json` on disk. Skill-key
dicts stay in memory only (matches the HTTP route which already skips the
vault for `skill_keys`). All callers — `/api/setup/complete`,
`/api/config/credentials`, `/api/llm/providers/{id}/configure` — keep the
same method contract; the write target changes underneath them.

**Files (5 max).**
1. `feral-core/config/loader.py` — rewrite `save_credentials`.
2. `feral-core/api/routes/llm.py` — fix the now-stale docstring on
   `configure_llm_provider` advertising the plaintext secondary store.
3. `feral-core/tests/test_no_plaintext_credentials_json_v2.py` — NEW
   regression: POST `/api/config/credentials`, assert `credentials.json`
   absent + `credentials.enc` present.
4. `feral-core/tests/test_config.py` — flip the one assertion in
   `test_save_credentials_sets_permissions` (it encodes the bug).
5. `docs/AGENT_PROMPTS_FOLLOWUPS.md` — one line: W24b.1 follow-up for
   `cli/setup_wizard.py` direct `write_text` sites (out of scope).
