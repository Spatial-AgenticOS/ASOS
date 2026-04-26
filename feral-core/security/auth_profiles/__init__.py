"""
W16 — per-agent auth profile store + multi-shape credentials.

See ``OPENCLAW_LESSONS.md`` §1 + §10 W16 for the architectural
rationale. Public surface re-exported below; submodule documentation
is intentionally verbose so you can read each file in isolation.
"""

from .external_auth import (
    EXTERNAL_CLI_ADAPTERS as EXTERNAL_CLI_ADAPTERS,
    has_external_cli_binary as has_external_cli_binary,
    list_external_credentials as list_external_credentials,
    overlay_external_credentials as overlay_external_credentials,
    probe_external_cli_version as probe_external_cli_version,
)
from .migrate import (
    LEGACY_BACKUP_SUFFIX as LEGACY_BACKUP_SUFFIX,
    MigrationResult as MigrationResult,
    run_migration_if_needed as run_migration_if_needed,
)
from .oauth_refresh_lock import (
    DEFAULT_TIMEOUT_SECONDS as DEFAULT_OAUTH_REFRESH_LOCK_TIMEOUT,
    OAuthRefreshLockTimeout as OAuthRefreshLockTimeout,
    acquire_oauth_refresh_lock as acquire_oauth_refresh_lock,
    resolve_oauth_refresh_lock_path as resolve_oauth_refresh_lock_path,
)
from .paths import (
    AUTH_PROFILES_FILENAME as AUTH_PROFILES_FILENAME,
    AUTH_STATE_FILENAME as AUTH_STATE_FILENAME,
    DEFAULT_AGENT_ID as DEFAULT_AGENT_ID,
    ensure_agent_dir as ensure_agent_dir,
    resolve_agent_dir as resolve_agent_dir,
    resolve_auth_profiles_path as resolve_auth_profiles_path,
    resolve_auth_state_path as resolve_auth_state_path,
    resolve_locks_dir as resolve_locks_dir,
    validate_agent_id as validate_agent_id,
)
from .store import AuthProfileFileStore as AuthProfileFileStore
from .types import (
    AUTH_PROFILE_STORE_VERSION as AUTH_PROFILE_STORE_VERSION,
    ApiKeyCredential as ApiKeyCredential,
    AuthProfileCredential as AuthProfileCredential,
    AuthProfileStore as AuthProfileStore,
    CREDENTIAL_TYPE_API_KEY as CREDENTIAL_TYPE_API_KEY,
    CREDENTIAL_TYPE_OAUTH as CREDENTIAL_TYPE_OAUTH,
    CREDENTIAL_TYPE_TOKEN as CREDENTIAL_TYPE_TOKEN,
    OAuthCredential as OAuthCredential,
    ProfileUsageStats as ProfileUsageStats,
    TokenCredential as TokenCredential,
    credential_from_dict as credential_from_dict,
)
from .usage import ProfileUsageTracker as ProfileUsageTracker
