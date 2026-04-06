#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager,
};

#[tauri::command]
fn start_brain() -> Result<String, String> {
    std::thread::spawn(|| {
        let status = std::process::Command::new("theora")
            .arg("serve")
            .spawn();
        match status {
            Ok(mut child) => {
                let _ = child.wait();
            }
            Err(e) => eprintln!("Failed to start Brain: {}", e),
        }
    });
    Ok("Brain server starting...".into())
}

#[tauri::command]
fn check_brain_health() -> Result<bool, String> {
    match reqwest::blocking::get("http://localhost:9090/health") {
        Ok(resp) => Ok(resp.status().is_success()),
        Err(_) => Ok(false),
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![start_brain, check_brain_health])
        .setup(|app| {
            let _tray = TrayIconBuilder::new()
                .tooltip("THEORA — Agentic OS")
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
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running THEORA Desktop");
}
