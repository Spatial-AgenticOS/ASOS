#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Emitter, Manager, State};
use tauri_plugin_global_shortcut::{Builder as GsBuilder, ShortcutState};

struct BrainProcess(pub Mutex<Option<Child>>);

fn resolve_asos_core_dir() -> Result<std::path::PathBuf, String> {
    if let Ok(dir) = std::env::var("ASOS_CORE_DIR") {
        return std::path::PathBuf::from(dir)
            .canonicalize()
            .map_err(|e| format!("ASOS_CORE_DIR invalid: {e}"));
    }
    let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../asos-core")
        .canonicalize()
        .map_err(|e| format!("asos-core path: {e}"))?;
    if !path.is_dir() {
        return Err(format!("asos-core not found at {}", path.display()));
    }
    Ok(path)
}

fn python_bin() -> &'static str {
    if cfg!(windows) {
        "python"
    } else {
        "python3"
    }
}

fn brain_base_url() -> String {
    std::env::var("THEORA_PUBLIC_BASE_URL")
        .or_else(|_| std::env::var("THEORA_BRAIN_URL"))
        .unwrap_or_else(|_| "http://localhost:9090".to_string())
}

#[tauri::command]
fn start_brain(state: State<'_, BrainProcess>) -> Result<u32, String> {
    let mut guard = state.0.lock().map_err(|e| format!("lock: {e}"))?;
    if let Some(mut existing) = guard.take() {
        let _ = existing.kill();
        let _ = existing.wait();
    }
    let dir = resolve_asos_core_dir()?;
    let mut cmd = Command::new(python_bin());
    cmd.current_dir(&dir)
        .args(["-m", "api.server"])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let child = cmd.spawn().map_err(|e| {
        format!(
            "failed to spawn {} -m api.server in {}: {e}",
            python_bin(),
            dir.display()
        )
    })?;
    let pid = child.id();
    *guard = Some(child);
    Ok(pid)
}

#[tauri::command]
fn stop_brain(state: State<'_, BrainProcess>, pid: u32) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| format!("lock: {e}"))?;
    if let Some(mut child) = guard.take() {
        if child.id() == pid {
            let _ = child.kill();
            let _ = child.wait();
            return Ok(());
        }
        *guard = Some(child);
    }
    kill_pid(pid).map_err(|e| e.to_string())
}

fn kill_pid(pid: u32) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        std::process::Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status()?;
    }
    #[cfg(windows)]
    {
        std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/F"])
            .status()?;
    }
    Ok(())
}

fn brain_health_probe() -> (bool, String) {
    let url = format!("{}/health", brain_base_url().trim_end_matches('/'));
    match reqwest::blocking::get(url) {
        Ok(resp) => {
            let code = resp.status().as_u16();
            let ok = resp.status().is_success();
            (ok, format!("HTTP {code}"))
        }
        Err(e) => (false, format!("unreachable: {e}")),
    }
}

#[tauri::command]
fn check_brain_health() -> Result<String, String> {
    let (_ok, status) = brain_health_probe();
    Ok(status)
}

#[tauri::command]
fn get_brain_url() -> String {
    brain_base_url()
}

fn main() {
    let shortcuts: &[&str] = if cfg!(target_os = "macos") {
        &["cmd+shift+t"]
    } else {
        &["ctrl+shift+t"]
    };
    let global_shortcut = GsBuilder::new()
        .with_shortcuts(shortcuts)
        .expect("register global shortcut definitions")
        .with_handler(|app, _shortcut, event| {
            if event.state == ShortcutState::Pressed {
                let _ = app.emit("voice-activation", ());
            }
        })
        .build();

    tauri::Builder::default()
        .plugin(global_shortcut)
        .manage(BrainProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            start_brain,
            stop_brain,
            check_brain_health,
            get_brain_url
        ])
        .setup(|app| {
            let tray = TrayIconBuilder::with_id("theora-tray")
                .title("THEORA")
                .tooltip("THEORA — starting…")
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            let tray_bg = tray.clone();
            std::thread::spawn(move || loop {
                let (ok, detail) = brain_health_probe();
                let dot = if ok { "🟢" } else { "🔴" };
                let tip = format!("THEORA — {dot} {detail}");
                let _ = tray_bg.set_tooltip(Some(tip.as_str()));
                std::thread::sleep(Duration::from_secs(2));
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running THEORA Desktop");
}
