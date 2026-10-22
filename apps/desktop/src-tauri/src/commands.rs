//! Tauri commands: the complete surface the UI can reach.

use std::path::PathBuf;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

use crate::engine::{EngineState, RpcError};
use crate::AppState;

/// Engine methods the UI may call with its own parameters. Anything that
/// takes a filesystem path is absent and handled by a dedicated command
/// that gets the path from the OS (dialog or drop).
pub const UI_METHODS: &[&str] = &[
    "health",
    "status",
    "search",
    "formats.list",
    "items.list",
    "items.get",
    "items.import_text",
    "items.delete",
    "items.retry",
    "jobs.cancel",
    "index.verify",
    "index.rebuild",
    "index.clear",
    "settings.get",
    "settings.update",
    "models.list",
    "models.download",
    "models.cancel",
];

pub fn ui_may_call(method: &str) -> bool {
    UI_METHODS.contains(&method)
}

#[tauri::command]
pub fn engine_state(state: State<'_, AppState>) -> EngineState {
    state.engine.state()
}

#[tauri::command]
pub fn engine_restart(state: State<'_, AppState>) {
    state.engine.restart();
}

#[tauri::command]
pub async fn engine_call(
    state: State<'_, AppState>,
    method: String,
    params: Option<Value>,
) -> Result<Value, RpcError> {
    if !ui_may_call(&method) {
        return Err(RpcError::local(
            "forbidden_method",
            "This action is not available from the UI",
        ));
    }
    state
        .engine
        .request(&method, params.unwrap_or_else(|| json!({})))
        .await
}

async fn import_paths(state: &AppState, paths: Vec<PathBuf>) -> Result<Value, RpcError> {
    let paths: Vec<String> = paths
        .into_iter()
        .map(|p| p.to_string_lossy().into_owned())
        .collect();
    if paths.is_empty() {
        return Ok(
            json!({ "queued": 0, "duplicates": 0, "rejected": [], "item_ids": [], "cancelled": true }),
        );
    }
    state
        .engine
        .request("items.import_paths", json!({ "paths": paths }))
        .await
}

/// Import paths that came from the OS (drag-and-drop) and report the result.
pub async fn import_os_paths(app: &AppHandle, paths: Vec<PathBuf>) {
    let state = app.state::<AppState>();
    let outcome = import_paths(&state, paths).await;
    let payload = match outcome {
        Ok(summary) => json!({ "ok": true, "summary": summary }),
        Err(err) => json!({ "ok": false, "error": err }),
    };
    let _ = app.emit("import://result", payload);
}

#[tauri::command]
pub async fn import_files(app: AppHandle, state: State<'_, AppState>) -> Result<Value, RpcError> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Import files into OmniRecall")
            .add_filter(
                "Supported documents",
                &[
                    "txt", "text", "log", "md", "markdown", "csv", "tsv", "json", "html", "htm",
                    "pdf", "docx",
                ],
            )
            .blocking_pick_files()
    })
    .await
    .map_err(|_| RpcError::local("dialog_failed", "The file dialog could not be opened"))?;
    let paths = picked
        .unwrap_or_default()
        .into_iter()
        .filter_map(|p| p.into_path().ok())
        .collect();
    import_paths(&state, paths).await
}

#[tauri::command]
pub async fn import_folder(app: AppHandle, state: State<'_, AppState>) -> Result<Value, RpcError> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Import a folder into OmniRecall")
            .blocking_pick_folder()
    })
    .await
    .map_err(|_| RpcError::local("dialog_failed", "The folder dialog could not be opened"))?;
    let paths = picked
        .and_then(|p| p.into_path().ok())
        .into_iter()
        .collect();
    import_paths(&state, paths).await
}

#[tauri::command]
pub async fn install_model_file(
    app: AppHandle,
    state: State<'_, AppState>,
    model_id: String,
) -> Result<Value, RpcError> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Choose the model file you downloaded")
            .add_filter("Model archive", &["gz", "tgz", "bin"])
            .blocking_pick_file()
    })
    .await
    .map_err(|_| RpcError::local("dialog_failed", "The file dialog could not be opened"))?;
    let Some(path) = picked.and_then(|p| p.into_path().ok()) else {
        return Ok(json!({ "cancelled": true }));
    };
    state
        .engine
        .request_with_timeout(
            "models.install_file",
            json!({ "model_id": model_id, "path": path.to_string_lossy() }),
            std::time::Duration::from_secs(600),
        )
        .await
}

/// Open the original file of an item with the system default app. The path
/// comes from the engine's record, never from the UI, and must still exist.
#[tauri::command]
pub async fn open_item_source(
    app: AppHandle,
    state: State<'_, AppState>,
    item_id: String,
) -> Result<(), RpcError> {
    let detail = state
        .engine
        .request("items.get", json!({ "item_id": item_id }))
        .await?;
    let source_type = detail["item"]["source_type"].as_str().unwrap_or_default();
    let uri = detail["item"]["source_uri"].as_str().unwrap_or_default();
    if source_type != "file" || uri.is_empty() {
        return Err(RpcError::local(
            "no_source",
            "This item has no original file",
        ));
    }
    let path = PathBuf::from(uri);
    if !path.is_file() {
        return Err(RpcError::local(
            "source_missing",
            "The original file was moved or deleted",
        ));
    }
    app.opener()
        .open_path(path.to_string_lossy(), None::<&str>)
        .map_err(|_| RpcError::local("open_failed", "The file could not be opened"))
}

#[tauri::command]
pub fn reveal_data_dir(app: AppHandle, state: State<'_, AppState>) -> Result<(), RpcError> {
    app.opener()
        .reveal_item_in_dir(&state.data_dir)
        .map_err(|_| RpcError::local("open_failed", "The folder could not be opened"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn path_taking_methods_are_not_ui_callable() {
        for method in [
            "items.import_paths",
            "models.install_file",
            "shutdown",
            "export.create",
            "anything",
        ] {
            assert!(!ui_may_call(method), "{method} must not be UI-callable");
        }
        assert!(ui_may_call("search"));
    }
}
