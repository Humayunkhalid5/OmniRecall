//! OmniRecall desktop shell: owns window lifecycle, the engine sidecar, and
//! OS integration. The UI reaches the engine only through the allow-listed
//! commands below.

mod engine;
mod paths;

use serde_json::Value;
use tauri::{Emitter, Manager, State};

use engine::{EngineEvent, EngineState, RestartPolicy, RpcError, Supervisor};

/// Engine methods the UI may call directly. Methods that take filesystem
/// paths are deliberately absent: those go through dedicated commands that
/// obtain paths from native dialogs or drop events, never from the UI.
const UI_METHODS: &[&str] = &["health", "status"];

struct AppState {
    engine: Supervisor,
}

#[tauri::command]
fn engine_state(state: State<'_, AppState>) -> EngineState {
    state.engine.state()
}

#[tauri::command]
fn engine_restart(state: State<'_, AppState>) {
    state.engine.restart();
}

#[tauri::command]
async fn engine_call(
    state: State<'_, AppState>,
    method: String,
    params: Option<Value>,
) -> Result<Value, RpcError> {
    if !UI_METHODS.contains(&method.as_str()) {
        return Err(RpcError::local(
            "forbidden_method",
            "This action is not available from the UI",
        ));
    }
    state
        .engine
        .request(&method, params.unwrap_or(Value::Object(Default::default())))
        .await
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
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
            app.manage(AppState { engine: supervisor });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine_state,
            engine_restart,
            engine_call
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
