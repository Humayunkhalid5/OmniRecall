//! OmniRecall desktop shell: owns window lifecycle, the engine sidecar, and
//! OS integration. The UI reaches the engine only through the allow-listed
//! commands in `commands.rs` (D-016).

mod commands;
mod engine;
mod paths;

use std::path::PathBuf;

use tauri::{DragDropEvent, Emitter, Manager, WindowEvent};

use engine::{EngineEvent, RestartPolicy, Supervisor};

pub struct AppState {
    pub engine: Supervisor,
    pub data_dir: PathBuf,
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let data_dir = app.path().app_data_dir()?;
            paths::prepare_data_dir(&data_dir)?;
            let handle = app.handle().clone();
            let supervisor = Supervisor::new(
                paths::engine_launch(&data_dir),
                RestartPolicy::default(),
                Box::new(move |event| match event {
                    EngineEvent::State(state) => {
                        let _ = handle.emit("engine://state", state);
                    }
                    EngineEvent::Notification(message) => {
                        let _ = handle.emit("engine://notification", message);
                    }
                }),
            );
            let runner = supervisor.clone();
            tauri::async_runtime::spawn(async move { runner.start() });
            app.manage(AppState {
                engine: supervisor,
                data_dir,
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            // Files dropped on the window come from the OS, not from page
            // script, so they may be imported (D-016).
            if let WindowEvent::DragDrop(DragDropEvent::Drop { paths, .. }) = event {
                let app = window.app_handle().clone();
                let paths = paths.clone();
                tauri::async_runtime::spawn(async move {
                    commands::import_os_paths(&app, paths).await;
                });
            }
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
        ])
        .build(tauri::generate_context!())
        .expect("error while building OmniRecall")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let engine = app.state::<AppState>().engine.clone();
                tauri::async_runtime::block_on(async move { engine.stop().await });
            }
        });
}
