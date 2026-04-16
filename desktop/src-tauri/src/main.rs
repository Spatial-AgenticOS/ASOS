#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Emitter, Manager, State};
use tauri_plugin_global_shortcut::{Builder as GsBuilder, ShortcutState};

struct BrainProcess(pub Mutex<Option<Child>>);

// ---------------------------------------------------------------------------
// Brain process helpers
// ---------------------------------------------------------------------------

fn resolve_feral_core_dir() -> Result<std::path::PathBuf, String> {
    if let Ok(dir) = std::env::var("FERAL_CORE_DIR") {
        return std::path::PathBuf::from(dir)
            .canonicalize()
            .map_err(|e| format!("FERAL_CORE_DIR invalid: {e}"));
    }
    let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../feral-core")
        .canonicalize()
        .map_err(|e| format!("feral-core path: {e}"))?;
    if !path.is_dir() {
        return Err(format!("feral-core not found at {}", path.display()));
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
    std::env::var("FERAL_PUBLIC_BASE_URL")
        .or_else(|_| std::env::var("FERAL_BRAIN_URL"))
        .unwrap_or_else(|_| "http://localhost:9090".to_string())
}

// ---------------------------------------------------------------------------
// Tauri commands — brain lifecycle
// ---------------------------------------------------------------------------

#[tauri::command]
fn start_brain(state: State<'_, BrainProcess>) -> Result<u32, String> {
    let mut guard = state.0.lock().map_err(|e| format!("lock: {e}"))?;
    if let Some(mut existing) = guard.take() {
        let _ = existing.kill();
        let _ = existing.wait();
    }
    let dir = resolve_feral_core_dir()?;
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

// ---------------------------------------------------------------------------
// Graceful brain shutdown
// ---------------------------------------------------------------------------

fn shutdown_brain(state: &BrainProcess) {
    if let Ok(mut guard) = state.0.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn toggle_floating_window(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("floating") {
        if w.is_visible().unwrap_or(false) {
            let _ = w.hide();
        } else {
            let _ = w.center();
            let _ = w.show();
            let _ = w.set_focus();
        }
    }
}

fn main() {
    let voice_shortcut: &[&str] = if cfg!(target_os = "macos") {
        &["cmd+shift+t"]
    } else {
        &["ctrl+shift+t"]
    };
    let floating_shortcut: &[&str] = if cfg!(target_os = "macos") {
        &["cmd+shift+f"]
    } else {
        &["ctrl+shift+f"]
    };

    let all_shortcuts: Vec<&str> = voice_shortcut
        .iter()
        .chain(floating_shortcut.iter())
        .copied()
        .collect();

    let floating_key = floating_shortcut[0].to_string();
    let global_shortcut = GsBuilder::new()
        .with_shortcuts(&all_shortcuts)
        .expect("register global shortcut definitions")
        .with_handler(move |app, shortcut, event| {
            if event.state == ShortcutState::Pressed {
                let key = shortcut.to_string().to_lowercase();
                if key.contains(&floating_key.to_lowercase()) {
                    toggle_floating_window(app);
                } else {
                    let _ = app.emit("voice-activation", ());
                }
            }
        })
        .build();

    tauri::Builder::default()
        .plugin(global_shortcut)
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--minimized"]),
        ))
        .manage(BrainProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            start_brain,
            stop_brain,
            check_brain_health,
            get_brain_url,
        ])
        .setup(|app| {
            // ---- System tray menu ----------------------------------------
            let show_hide = MenuItem::with_id(
                app,
                "show_hide",
                "Show / Hide FERAL",
                true,
                None::<&str>,
            )?;
            let spotlight = MenuItem::with_id(
                app,
                "spotlight",
                "Spotlight Chat  (Cmd+Shift+F)",
                true,
                None::<&str>,
            )?;
            let quick_chat = MenuItem::with_id(
                app,
                "quick_chat",
                "Quick Chat",
                true,
                None::<&str>,
            )?;
            let quit =
                MenuItem::with_id(app, "quit", "Quit FERAL", true, None::<&str>)?;

            let menu = Menu::with_items(
                app,
                &[
                    &show_hide,
                    &spotlight,
                    &PredefinedMenuItem::separator(app)?,
                    &quick_chat,
                    &PredefinedMenuItem::separator(app)?,
                    &quit,
                ],
            )?;

            let tray = TrayIconBuilder::with_id("feral-tray")
                .title("FERAL")
                .tooltip("FERAL — starting…")
                .menu(&menu)
                .menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show_hide" => {
                        if let Some(w) = app.get_webview_window("main") {
                            if w.is_visible().unwrap_or(false) {
                                let _ = w.hide();
                            } else {
                                let _ = w.show();
                                let _ = w.set_focus();
                            }
                        }
                    }
                    "spotlight" => {
                        toggle_floating_window(app);
                    }
                    "quick_chat" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                            let _ = app.emit("voice-activation", ());
                        }
                    }
                    "quit" => {
                        if let Some(bp) = app.try_state::<BrainProcess>() {
                            shutdown_brain(bp.inner());
                        }
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                })
                .build(app)?;

            // ---- Background health tooltip loop --------------------------
            let tray_bg = tray.clone();
            std::thread::spawn(move || loop {
                let (ok, detail) = brain_health_probe();
                let dot = if ok { "🟢" } else { "🔴" };
                let tip = format!("FERAL — {dot} {detail}");
                let _ = tray_bg.set_tooltip(Some(tip.as_str()));
                std::thread::sleep(Duration::from_secs(2));
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(bp) = window.app_handle().try_state::<BrainProcess>() {
                    shutdown_brain(bp.inner());
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running FERAL Desktop");
}
