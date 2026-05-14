"""
``feral key`` — vault key lifecycle CLI (W9).

Subcommands:
  - ``feral key status``  — show vault status (encrypted? master key
                            in keychain? legacy backup? rotation backup?)
  - ``feral key rotate``  — generate a new master key, re-encrypt the
                            vault, swap atomically, print the new
                            recovery code (shown ONCE).
  - ``feral key recover`` — restore the OS keychain master key from a
                            written-down recovery code. Use this when
                            the keychain is wiped (new laptop, OS
                            reinstall, accidental delete).

These commands are wired into ``feral`` via :func:`register_key_subparser`
which is invoked from ``cli/main.py``. Doing the registration in this
file keeps the CLI surface for the security path testable without
importing the whole brain.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from cli import ui_kit


# ─────────────────────────────────────────────────────────────────────
# Argparse registration (called from cli/main.py)
# ─────────────────────────────────────────────────────────────────────


def register_key_subparser(sub: "argparse._SubParsersAction") -> None:
    """Register `feral key {status,rotate,recover}` under the main
    `feral` argparse subparsers group."""
    key_p = sub.add_parser(
        "key",
        help="Manage the encrypted credential vault (status, rotate, recover)",
    )
    key_sub = key_p.add_subparsers(dest="action")

    key_sub.add_parser(
        "status",
        help="Show vault status: encrypted on disk, master key in keychain, "
             "presence of legacy/rotation backups.",
    )

    rotate_p = key_sub.add_parser(
        "rotate",
        help="Generate a new master key, re-encrypt the vault, and print "
             "a fresh recovery code (shown ONCE).",
    )
    rotate_p.add_argument(
        "--yes",
        action="store_true",
        dest="key_confirm",
        help="Skip the interactive confirmation prompt (use in scripts).",
    )

    recover_p = key_sub.add_parser(
        "recover",
        help="Restore the OS keychain master key from a written-down "
             "recovery code (when the keychain entry is wiped).",
    )
    recover_p.add_argument(
        "--code",
        default="",
        help="Recovery code; if omitted, you will be prompted "
             "interactively (recommended — paste-from-terminal-history "
             "leaves the secret in your shell history).",
    )

    # ── W16 additions ───────────────────────────────────────────────
    # The three subcommands below were added by W16. They are additive:
    # the W9 `status`/`rotate`/`recover` behaviour above is unchanged.

    list_p = key_sub.add_parser(
        "list",
        help="List per-agent auth profiles (W16). Shows profile ids and "
             "credential types; never echoes secrets.",
    )
    list_p.add_argument(
        "--agent",
        default=None,
        help="Agent id whose profiles to list (default: 'default').",
    )

    key_sub.add_parser(
        "migrate",
        help="W16: import the legacy ~/.feral/credentials.json blob "
             "into the new per-agent auth profile store. Idempotent.",
    )

    # W16: extend `feral key rotate` with `--provider` so a single
    # per-agent credential can be rotated without touching the W9 vault
    # master key. When `--provider` is omitted the W9 master-key
    # rotation behaviour above is preserved verbatim.
    rotate_p.add_argument(
        "--provider",
        default=None,
        help="W16: rotate ONE provider's credential in the per-agent "
             "auth profile store. When set, this overrides the master-key "
             "rotation default.",
    )
    rotate_p.add_argument(
        "--agent",
        default=None,
        help="W16: agent id whose profile to rotate (default: 'default'). "
             "Only meaningful with --provider.",
    )
    rotate_p.add_argument(
        "--key",
        default=None,
        help="W16: new API key value. Only meaningful with --provider; "
             "if omitted, prompted via masked-character input.",
    )


def dispatch_key_subcommand(args) -> int:
    action = getattr(args, "action", None) or "status"
    if action == "status":
        return cmd_key_status()
    if action == "rotate":
        # W16: when --provider is supplied, rotate that single per-agent
        # credential instead of the vault master key. The W9 master-key
        # path is preserved exactly when --provider is absent.
        provider = getattr(args, "provider", None)
        if provider:
            return cmd_key_rotate_provider(
                provider=provider,
                agent_id=getattr(args, "agent", None),
                new_key=getattr(args, "key", None),
            )
        return cmd_key_rotate(skip_confirm=getattr(args, "key_confirm", False))
    if action == "recover":
        return cmd_key_recover(code=getattr(args, "code", "") or "")
    if action == "list":
        return cmd_key_list(agent_id=getattr(args, "agent", None))
    if action == "migrate":
        return cmd_key_migrate()
    print(
        f"Unknown action: {action}. "
        f"Try one of: status, rotate, recover, list, migrate."
    )
    return 2


# ─────────────────────────────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────────────────────────────


def cmd_key_status() -> int:
    """Print a one-screen vault report. Never echoes secrets."""
    from security.vault import get_vault, VaultError

    try:
        v = get_vault()
    except VaultError as exc:
        print("  feral key status — vault unavailable")
        print()
        print(f"  Error: {exc}")
        print()
        print("  Resolution: run `feral key recover` and supply your")
        print("  recovery code (the one you wrote down at first boot or")
        print("  after the most recent `feral key rotate`).")
        return 1

    s = v.status()
    print("  FERAL Vault — Status")
    print("  " + "=" * 40)
    print(f"  Encrypted file : {'yes' if s['encrypted'] else 'no (no vault yet)'}")
    print(f"  Path           : {s['encrypted_path']}")
    print(f"  Master key     : {'in OS keychain' if s['keychain'] else 'NOT in keychain'}")
    print(f"  Keychain entry : service={s['keychain_service']!r}, "
          f"user={s['keychain_user']!r}")
    print(f"  Legacy backup  : {'present (' + s['legacy_backup_path'] + ')' if s['legacy_backup'] else 'none'}")
    print(f"  Rotation prev  : {'present (' + s['prev_backup_path'] + ')' if s['prev_backup'] else 'none'}")
    print(f"  Namespaces     : {', '.join(s['namespaces']) or '(empty)'}")
    print(f"  Stored keys    : {s['key_count']}")

    code = v.consume_first_boot_recovery_code()
    if code:
        _print_recovery_code(code, occasion="first boot")

    if not s["keychain"] and s["encrypted"]:
        print()
        print("  WARNING: vault is encrypted on disk but the OS keychain has")
        print("  no master key. The brain will refuse to start until you run")
        print("  `feral key recover` (or set FERAL_VAULT_RECOVERY_CODE).")
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────
# Rotate
# ─────────────────────────────────────────────────────────────────────


def cmd_key_rotate(*, skip_confirm: bool = False) -> int:
    """Generate a new master key, re-encrypt the vault under it, swap
    atomically, print the new recovery code."""
    from security.vault import get_vault, VaultError

    try:
        v = get_vault()
    except VaultError as exc:
        print(f"  Cannot rotate: {exc}")
        return 1

    if not skip_confirm:
        ui_kit.brand_panel(
            "feral key rotate",
            body=(
                "About to rotate the vault master key.\n"
                "  - Previous master key will be REMOVED from the OS keychain.\n"
                "  - credentials.enc.prev kept until the next successful brain boot.\n"
                "  - A new recovery code will be printed ONCE. Write it down."
            ),
        )
        try:
            if not ui_kit.confirm("Continue with rotation?", default=False):
                print("  Cancelled.")
                return 1
        except KeyboardInterrupt:
            print()
            print("  Cancelled.")
            return 1

    try:
        new_code = v.rotate_master_key()
    except VaultError as exc:
        print()
        print(f"  Rotation FAILED: {exc}")
        print()
        print("  The vault file was NOT modified. Resolve the underlying")
        print("  issue (usually OS keychain access) and re-run.")
        return 1

    _print_recovery_code(new_code, occasion="rotation")
    return 0


# ─────────────────────────────────────────────────────────────────────
# Recover
# ─────────────────────────────────────────────────────────────────────


def cmd_key_recover(*, code: str = "") -> int:
    """Restore the OS keychain master key from a recovery code."""
    from security.vault import get_vault, VaultError, decode_recovery_code

    if not code:
        ui_kit.brand_panel(
            "feral key recover",
            body=(
                "Paste the recovery code you wrote down at first boot "
                "(or the most recent `feral key rotate`).\n"
                "Format: ABCD-EFGH-IJKL-MNOP-… (13 groups). "
                "Each character is masked as you paste."
            ),
        )
        try:
            code = ui_kit.password("Recovery code", allow_empty=False).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print("  Cancelled.")
            return 1

    if not code:
        print("  No recovery code supplied. Aborting.")
        return 1

    try:
        decode_recovery_code(code)
    except ValueError as exc:
        print(f"  Recovery code is malformed: {exc}")
        return 1

    # Construct the vault. The decryption attempt happens inside
    # restore_from_recovery_code so we report a single, clear error if
    # the code doesn't actually decrypt the file.
    try:
        v = get_vault()
    except VaultError:
        # Expected: the keychain is empty AND .enc exists, so the
        # default constructor refused to start. Reach in via a manual
        # construction with the recovery code applied so we can call
        # restore_from_recovery_code(...).
        os.environ["FERAL_VAULT_RECOVERY_CODE"] = code
        from security.vault import reset_vault, get_vault as _gv
        reset_vault()
        try:
            v = _gv()
        except VaultError as exc:
            print(f"  Recovery FAILED: {exc}")
            return 1

    try:
        v.restore_from_recovery_code(code)
    except VaultError as exc:
        print(f"  Recovery FAILED: {exc}")
        print()
        print("  The OS keychain was NOT modified. Double-check the code")
        print("  (case-insensitive, dashes/spaces ignored) and re-run.")
        return 1

    print("  Recovery succeeded.")
    print("  The OS keychain now holds the master key for this vault.")
    print("  You can run `feral key status` to confirm.")
    return 0


# ─────────────────────────────────────────────────────────────────────
# Recovery-code printing helper
# ─────────────────────────────────────────────────────────────────────


def _print_recovery_code(code: str, *, occasion: str) -> None:
    """Render the recovery code with framing so the user notices it.

    NEVER logged. NEVER echoed twice. The caller controls when this is
    invoked; in particular `cmd_key_status` only prints the first-boot
    code at the moment of vault construction (via
    ``consume_first_boot_recovery_code``), then forgets it.
    """
    bar = "  " + "─" * 60
    print()
    print(bar)
    print(f"  RECOVERY CODE — {occasion} (shown ONCE)")
    print(bar)
    print()
    print(f"     {code}")
    print()
    print("  Write this down NOW (paper, password manager, vault).")
    print("  It is the ONLY way to recover credentials if the OS keychain")
    print("  entry is lost. FERAL has no escrow copy.")
    print(bar)


# ─────────────────────────────────────────────────────────────────────
# W16: per-agent auth profile commands (additive — never modify the
# W9 status/rotate/recover behaviour above).
# ─────────────────────────────────────────────────────────────────────


def cmd_key_list(*, agent_id: Optional[str] = None) -> int:
    """List the per-agent auth profiles (id + credential type + provider).

    Never echoes the secret material; the most a row ever shows is the
    fingerprint-style "*****abcd" tail of the key so an operator can
    confirm "yes that's the key I think it is".
    """
    from security.auth_profiles import (
        AuthProfileFileStore,
        DEFAULT_AGENT_ID,
        validate_agent_id,
    )
    from security.auth_profiles.types import (
        ApiKeyCredential,
        OAuthCredential,
        TokenCredential,
    )

    cleaned = validate_agent_id(agent_id or DEFAULT_AGENT_ID)
    store = AuthProfileFileStore(cleaned)
    profiles = store.load()

    print(f"  FERAL Auth Profiles — agent: {cleaned}")
    print("  " + "=" * 60)
    if not profiles:
        print("  (no profiles registered)")
        print()
        print("  Tip: run `feral key migrate` to import the legacy")
        print("       ~/.feral/credentials.json blob, or use the Settings")
        print("       UI to add a credential.")
        return 0

    for profile_id in sorted(profiles.keys()):
        cred = profiles[profile_id]
        if isinstance(cred, ApiKeyCredential):
            tail = cred.key[-4:] if len(cred.key) >= 4 else "****"
            print(f"  {profile_id:<32}  api_key   {cred.provider:<16}  *****{tail}")
        elif isinstance(cred, OAuthCredential):
            print(
                f"  {profile_id:<32}  oauth     {cred.provider:<16}  "
                f"refresh stored, expires_ms={cred.expires}"
            )
        elif isinstance(cred, TokenCredential):
            tail = cred.token[-4:] if len(cred.token) >= 4 else "****"
            print(f"  {profile_id:<32}  token     {cred.provider:<16}  *****{tail}")
        else:
            print(f"  {profile_id:<32}  unknown   {type(cred).__name__}")
    return 0


def cmd_key_migrate() -> int:
    """Manually trigger the W16 legacy → per-agent migration."""
    from security.auth_profiles import run_migration_if_needed

    result = run_migration_if_needed()
    if not result.migrated:
        if result.noop_reason == "already-migrated":
            print(f"  Already migrated: {result.destination}")
            print("  (no-op; per-agent file already exists)")
            return 0
        if result.noop_reason == "no-legacy-file":
            print(f"  Nothing to migrate: {result.legacy_path} does not exist.")
            return 0
        print(f"  No migration performed (reason={result.noop_reason}).")
        return 0

    print("  W16 migration complete.")
    print(f"    Source       : {result.legacy_path}")
    print(f"    Destination  : {result.destination}")
    print(f"    Backup       : {result.backup_path}  (mode 0600)")
    print(f"    Entries      : {result.entries} ({result.api_keys} api_key, "
          f"{result.oauth} oauth)")
    print()
    print("  The original credentials.json was NOT deleted — W9 still owns")
    print("  that file's lifecycle. Once you've verified the per-agent file")
    print("  loads correctly, the W9 vault path will rotate it out on its")
    print("  next encryption migration.")
    return 0


def cmd_key_rotate_provider(
    *,
    provider: str,
    agent_id: Optional[str] = None,
    new_key: Optional[str] = None,
) -> int:
    """W16 — rotate one provider's credential in the per-agent store.

    Today only the API-key shape is rotatable from the CLI: OAuth
    rotation needs the provider's authorisation server in the loop and
    is the user-facing flow's responsibility. Token rotation is a
    delete + insert and so is structurally identical to API-key rotate.
    """
    from security.auth_profiles import AuthProfileFileStore, validate_agent_id
    from security.auth_profiles.types import (
        ApiKeyCredential,
        OAuthCredential,
        TokenCredential,
    )

    cleaned = validate_agent_id(agent_id or "default")
    store = AuthProfileFileStore(cleaned)
    existing = store.get(provider)
    if existing is None:
        print(
            f"  No profile {provider!r} registered for agent {cleaned!r}. "
            f"Add the credential first via Settings or `feral key migrate`."
        )
        return 1

    if isinstance(existing, OAuthCredential):
        print(
            "  OAuth rotation must go through the provider's authorisation "
            "server (browser flow). Use the Settings UI to re-authenticate, "
            "or revoke + re-add the profile."
        )
        return 1

    if not new_key:
        ui_kit.brand_panel(
            f"feral key rotate — {provider}",
            body=(
                f"Paste the NEW key for provider {provider!r}, agent "
                f"{cleaned!r}. Each character is masked as you paste."
            ),
        )
        try:
            new_key = ui_kit.password("New key", allow_empty=False).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print("  Cancelled.")
            return 1

    if not new_key:
        print("  No key supplied. Aborting.")
        return 1

    if isinstance(existing, ApiKeyCredential):
        rotated: ApiKeyCredential | TokenCredential = ApiKeyCredential(
            provider=existing.provider,
            key=new_key,
            email=existing.email,
            display_name=existing.display_name,
            metadata=dict(existing.metadata),
        )
    elif isinstance(existing, TokenCredential):
        rotated = TokenCredential(
            provider=existing.provider,
            token=new_key,
            expires=existing.expires,
            email=existing.email,
            display_name=existing.display_name,
        )
    else:
        print(f"  Unsupported credential shape {type(existing).__name__}.")
        return 1

    store.upsert(provider, rotated)
    print(f"  Rotated {provider!r} for agent {cleaned!r}.")
    return 0


# ─────────────────────────────────────────────────────────────────────
# Stand-alone entry point (for `python -m cli.key_commands ...`)
# ─────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Run a single `feral key …` command from a fresh argv. Mirrors
    the dispatch logic in cli/main.py so this module is testable in
    isolation."""
    parser = argparse.ArgumentParser(prog="feral key")
    sub = parser.add_subparsers(dest="subcommand")

    # The key_commands module owns the `key` subparser; reuse it here
    # by registering against a dummy "wrapper" so `argparse` builds the
    # action layer the same way cli/main.py does.
    register_key_subparser(sub)

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.subcommand != "key":
        parser.print_help()
        return 2
    return dispatch_key_subcommand(args)


if __name__ == "__main__":
    raise SystemExit(main())
