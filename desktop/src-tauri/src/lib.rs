//! Smoke harness for the FERAL desktop crate.
//!
//! W10 (Roadmap §3.2 #5) gates `desktop/` on per-PR CI for the first
//! time. To make `cargo test` non-trivial we expose a minimal helper
//! that loads `tauri.conf.json` and pulls out the fields a release
//! cares about (version, identifier, the `app.security.csp`). The
//! integration test in `tests/smoke.rs` calls these helpers; the
//! `#[cfg(test)]` module in this file double-checks them as a unit test.
//!
//! The harness intentionally does NOT depend on the `tauri` crate —
//! we only need `serde_json` so the test build is fast and can run on
//! a runner without a desktop session. The full Tauri build still
//! happens in the workflow's `build` job.

use std::path::Path;

use serde_json::Value;

/// Default location of `tauri.conf.json` relative to the package root.
pub const DEFAULT_CONFIG_PATH: &str = "tauri.conf.json";

/// Errors that can surface when reading or parsing the Tauri config.
#[derive(Debug)]
pub enum ConfigLoadError {
    /// The file could not be opened or read.
    Io(String),
    /// The file contents were not valid JSON.
    Parse(String),
    /// A required top-level field was missing or had the wrong type.
    MissingField(&'static str),
}

impl std::fmt::Display for ConfigLoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConfigLoadError::Io(msg) => write!(f, "io error: {msg}"),
            ConfigLoadError::Parse(msg) => write!(f, "json parse error: {msg}"),
            ConfigLoadError::MissingField(name) => {
                write!(f, "tauri.conf.json: required field missing: {name}")
            }
        }
    }
}

impl std::error::Error for ConfigLoadError {}

/// Read and parse a Tauri config file at `path`.
pub fn load_tauri_config<P: AsRef<Path>>(path: P) -> Result<Value, ConfigLoadError> {
    let raw = std::fs::read_to_string(path.as_ref())
        .map_err(|e| ConfigLoadError::Io(format!("{}: {e}", path.as_ref().display())))?;
    serde_json::from_str(&raw).map_err(|e| ConfigLoadError::Parse(e.to_string()))
}

/// Pull the top-level `version` string out of a Tauri config.
pub fn extract_version(cfg: &Value) -> Result<String, ConfigLoadError> {
    cfg.get("version")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or(ConfigLoadError::MissingField("version"))
}

/// Pull the top-level `identifier` (reverse-DNS bundle id) string out
/// of a Tauri config.
pub fn extract_identifier(cfg: &Value) -> Result<String, ConfigLoadError> {
    cfg.get("identifier")
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or(ConfigLoadError::MissingField("identifier"))
}

/// Pull the `app.security.csp` string out of a Tauri config. Used by
/// the smoke test to make sure no future PR drops the explicit CSP
/// (Roadmap §3.3 #2 — sandbox AppSurface).
pub fn extract_csp(cfg: &Value) -> Result<String, ConfigLoadError> {
    cfg.get("app")
        .and_then(|app| app.get("security"))
        .and_then(|sec| sec.get("csp"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or(ConfigLoadError::MissingField("app.security.csp"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn load() -> Value {
        load_tauri_config(DEFAULT_CONFIG_PATH).expect("tauri.conf.json should load")
    }

    #[test]
    fn config_file_loads_from_package_root() {
        let cfg = load();
        assert!(cfg.is_object(), "config root must be a JSON object");
    }

    #[test]
    fn version_is_present_and_non_empty() {
        let cfg = load();
        let v = extract_version(&cfg).expect("version field present");
        assert!(!v.trim().is_empty(), "version must not be empty");
    }

    #[test]
    fn identifier_uses_reverse_dns_under_ai_feral() {
        let cfg = load();
        let id = extract_identifier(&cfg).expect("identifier field present");
        assert!(
            id.starts_with("ai.feral"),
            "identifier should start with ai.feral; got {id}"
        );
    }

    #[test]
    fn csp_is_explicitly_set() {
        let cfg = load();
        let csp = extract_csp(&cfg).expect("app.security.csp present");
        assert!(csp.contains("default-src"), "CSP missing default-src");
        assert!(
            csp.contains("connect-src"),
            "CSP missing connect-src — brain WS would be blocked"
        );
    }

    #[test]
    fn missing_field_error_displays_helpfully() {
        let empty: Value = serde_json::json!({});
        let err = extract_version(&empty).unwrap_err();
        let rendered = format!("{err}");
        assert!(
            rendered.contains("version"),
            "error message should name the missing field; got: {rendered}"
        );
    }
}
