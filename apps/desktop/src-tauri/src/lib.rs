//! OmniRecall desktop shell: owns window lifecycle, the engine sidecar, and
//! OS integration. The UI reaches the engine only through the allow-listed
//! commands in `commands.rs` (D-016).

mod capture;
mod commands;
mod engine;
mod paths;
mod tray;

use std::path::PathBuf;
use std::sync::Mutex;

use serde_json::{json, Value};
use tauri::{AppHandle, DragDropEvent, Emitter, Manager, WindowEvent};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

use capture::ClipboardWatcher;
use engine::{EngineEvent, EngineState, RestartPolicy, Supervisor};
use tray::{CaptureSummary, Tray, PAUSE_SHORTCUT};

pub struct AppState {
    pub engine: Supervisor,
    pub data_dir: PathBuf,
    pub watcher: ClipboardWatcher,
    pub capture: Mutex<CaptureSummary>,
    pub shortcut_registered: bool,
}

/// Apply the engine's capture state to the watcher and the indicator.
fn apply_capture(app: &AppHandle, summary: CaptureSummary) {
    if let Some(state) = app.try_state::<AppState>() {
        state.watcher.set_active(summary.clipboard_active);
        *state.capture.lock().expect("capture lock") = summary.clone();
    }
    tray::update(app, &summary);
}

fn refresh_capture(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let Some(state) = app.try_state::<AppState>() else {
            return;
        };
        match state.engine.request("capture.state", json!({})).await {
            Ok(value) => apply_capture(&app, CaptureSummary::from_state(&value)),
            Err(_) => apply_capture(&app, CaptureSummary::OFF),
        }
    });
}

/// Pause or resume all capture (tray menu and global shortcut).
pub fn toggle_pause(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let Some(state) = app.try_state::<AppState>() else {
            return;
        };
        let paused = state.capture.lock().expect("capture lock").paused;
        if let Ok(value) = state
            .engine
            .request("capture.pause", json!({ "paused": !paused }))
            .await
        {
            apply_capture(&app, CaptureSummary::from_state(&value));
        }
    });
}

pub fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub fn quit(app: &AppHandle) {
    app.exit(0);
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main_window(app);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        toggle_pause(app);
                    }
                })
                .build(),
        )
        .setup(|app| {
            let data_dir = app.path().app_data_dir()?;
            paths::prepare_data_dir(&data_dir)?;
            let handle = app.handle().clone();
            let supervisor = Supervisor::new(
                paths::engine_launch(&data_dir),
                RestartPolicy::default(),
                Box::new(move |event| match event {
                    EngineEvent::State(state) => {
                        // Capture follows the engine: off whenever it is not running.
                        if matches!(state, EngineState::Running { .. }) {
                            refresh_capture(&handle);
                        } else {
                            apply_capture(&handle, CaptureSummary::OFF);
                        }
                        let _ = handle.emit("engine://state", state);
                    }
                    EngineEvent::Notification(message) => {
                        if message["method"] == "capture.state" {
                            let params: &Value = &message["params"];
                            apply_capture(&handle, CaptureSummary::from_state(params));
                        }
                        let _ = handle.emit("engine://notification", message);
                    }
                }),
            );
            let watcher = ClipboardWatcher::spawn(supervisor.clone());
            // Another app may own the shortcut, or the platform may not
            // support global shortcuts (Wayland); the tray and the window
            // still pause capture.
            let shortcut_registered = app.global_shortcut().register(PAUSE_SHORTCUT).is_ok();
            app.manage(AppState {
                engine: supervisor.clone(),
                data_dir,
                watcher,
                capture: Mutex::new(CaptureSummary::OFF),
                shortcut_registered,
            });
            // Without a tray host (some Linux desktops) the window header
            // remains the capture indicator.
            if let Ok(tray) = Tray::build(app.handle()) {
                app.manage(tray);
            }
            tauri::async_runtime::spawn(async move { supervisor.start() });
            Ok(())
        })
        .on_window_event(|window, event| match event {
            // Files dropped on the window come from the OS, not from page
            // script, so they may be imported (D-016).
            WindowEvent::DragDrop(DragDropEvent::Drop { paths, .. }) => {
                let app = window.app_handle().clone();
                let paths = paths.clone();
                tauri::async_runtime::spawn(async move {
                    commands::import_os_paths(&app, paths).await;
                });
            }
            // While a capture source is enabled the app keeps running in the
            // tray, where the indicator stays visible; Quit is in its menu.
            // Without a tray, closing the window quits and capture stops.
            WindowEvent::CloseRequested { api, .. } => {
                let app = window.app_handle();
                let state = app.state::<AppState>();
                let has_tray = app.try_state::<Tray>().is_some();
                let keep_running =
                    has_tray && state.capture.lock().expect("capture lock").any_enabled;
                if keep_running {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            commands::engine_state,
            commands::engine_restart,
            commands::engine_call,
            commands::import_files,
            commands::import_folder,
            commands::install_model_file,
            commands::open_item_source,
            commands::reveal_data_dir,
            commands::export_data,
            commands::add_folder_exclusion,
            commands::pause_shortcut,
        ])
        .build(tauri::generate_context!())
        .expect("error while building OmniRecall")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let state = app.state::<AppState>();
                state.watcher.set_active(false);
                let engine = state.engine.clone();
                tauri::async_runtime::block_on(async move { engine.stop().await });
            }
        });
}
