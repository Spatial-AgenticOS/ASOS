//! Integration smoke test for the FERAL desktop crate.
//!
//! W10 (Roadmap §3.2 #5): the desktop tree had ZERO tests prior to this
//! workstream. This integration test asserts that `tauri.conf.json`
//! loads cleanly and exposes the fields downstream releases depend on
//! (version, identifier, security.csp).
//!
//! Runs as a separate test crate against `feral_desktop`'s public lib
//! API, so a regression in either the file shape or the harness API
//! is caught from both sides.

use feral_desktop::{
    extract_csp, extract_identifier, extract_version, load_tauri_config, DEFAULT_CONFIG_PATH,
};

#[test]
fn tauri_config_loads_and_has_version_and_identifier() {
    let cfg = load_tauri_config(DEFAULT_CONFIG_PATH)
        .expect("tauri.conf.json should load from src-tauri/ working dir");

    let version = extract_version(&cfg).expect("version field present");
    let identifier = extract_identifier(&cfg).expect("identifier field present");

    assert!(
        !version.trim().is_empty(),
        "version must not be empty (release scripts depend on it)"
    );
    assert!(
        !identifier.trim().is_empty(),
        "identifier must not be empty (mac/win bundle ids depend on it)"
    );
    assert!(
        identifier.starts_with("ai.feral"),
        "identifier should start with ai.feral; got {identifier}"
    );
}

#[test]
fn tauri_config_csp_is_set() {
    // Sandbox of the desktop window depends on the CSP being explicitly
    // configured; W8 (Roadmap §3.3 #2) tightens the AppSurface CSP and
    // we want a regression here to fail loudly.
    let cfg =
        load_tauri_config(DEFAULT_CONFIG_PATH).expect("tauri.conf.json should load");
    let csp = extract_csp(&cfg).expect("app.security.csp must be set");
    assert!(
        csp.contains("default-src"),
        "CSP must contain default-src directive; got {csp}"
    );
}

#[test]
fn missing_config_path_returns_io_error_rather_than_panic() {
    let result = load_tauri_config("does-not-exist.json");
    assert!(
        result.is_err(),
        "loading a non-existent config must return Err, not panic"
    );
}
