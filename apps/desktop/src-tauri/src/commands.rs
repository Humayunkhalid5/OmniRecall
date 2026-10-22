//! Tauri commands: the complete surface the UI can reach.

use std::path::PathBuf;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

use crate::engine::{EngineState, RpcError};
use crate::screenshot::ScreenshotStatus;
use crate::AppState;

/// Largest preview handed to the UI; thumbnails are far smaller.
const MAX_PREVIEW_BYTES: u64 = 8 * 1024 * 1024;

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
    "capture.state",
    "capture.set_source",
    "capture.pause",
    "exclusions.list",
    "exclusions.add",
    "exclusions.update",
    "exclusions.remove",
    "storage.usage",
    "database.recover",
    "database.reset",
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

// The engine's formats.list is the authority; these only pre-filter the dialog.
const DOCUMENT_EXTENSIONS: &[&str] = &[
    "txt", "text", "log", "md", "markdown", "csv", "tsv", "json", "html", "htm", "pdf", "docx",
];
const IMAGE_EXTENSIONS: &[&str] = &["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif"];
const AUDIO_EXTENSIONS: &[&str] = &[
    "wav", "wave", "mp3", "m4a", "aac", "flac", "ogg", "oga", "aif", "aiff", "caf",
];

#[tauri::command]
pub async fn import_files(app: AppHandle, state: State<'_, AppState>) -> Result<Value, RpcError> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Import files into OmniRecall")
            .add_filter(
                "All supported files",
                &[DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, AUDIO_EXTENSIONS].concat(),
            )
            .add_filter("Documents", DOCUMENT_EXTENSIONS)
            .add_filter("Images (text is read with OCR)", IMAGE_EXTENSIONS)
            .add_filter("Audio (transcribed on this device)", AUDIO_EXTENSIONS)
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
    if source_type == "screenshot" {
        let path = owned_media(&state, &detail["item"], false).ok_or_else(|| {
            RpcError::local("media_missing", "The screenshot image is no longer kept")
        })?;
        return app
            .opener()
            .open_path(path.to_string_lossy(), None::<&str>)
            .map_err(|_| RpcError::local("open_failed", "The image could not be opened"));
    }
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

/// The app-owned media file (or its thumbnail) of an item, only if it resolves
/// inside the media folder. The relative path comes from the engine's record.
fn owned_media(state: &AppState, item: &Value, thumbnail: bool) -> Option<PathBuf> {
    if item["media_status"].as_str() != Some("present") {
        return None;
    }
    let uri = item["media_uri"].as_str()?;
    let root = state.data_dir.join("media").canonicalize().ok()?;
    let mut path = root.join(uri);
    if thumbnail {
        let stem = path.file_stem()?.to_string_lossy().into_owned();
        path = path.with_file_name(format!("{stem}.thumb.webp"));
    }
    let resolved = path.canonicalize().ok()?;
    (resolved.starts_with(&root) && resolved.is_file()).then_some(resolved)
}

/// A screenshot's preview as a data URL, or null when the image is not kept.
#[tauri::command]
pub async fn item_preview(
    state: State<'_, AppState>,
    item_id: String,
) -> Result<Option<String>, RpcError> {
    use base64::Engine as _;

    let detail = state
        .engine
        .request("items.get", json!({ "item_id": item_id }))
        .await?;
    let item = &detail["item"];
    if item["source_type"].as_str() != Some("screenshot") {
        return Ok(None);
    }
    let (path, mime) = match owned_media(&state, item, true) {
        Some(thumb) => (thumb, "image/webp"),
        None => match owned_media(&state, item, false) {
            Some(full) => (full, "image/png"),
            None => return Ok(None),
        },
    };
    let bytes = tauri::async_runtime::spawn_blocking(move || -> Option<Vec<u8>> {
        let size = std::fs::metadata(&path).ok()?.len();
        (size <= MAX_PREVIEW_BYTES).then(|| std::fs::read(&path).ok())?
    })
    .await
    .ok()
    .flatten();
    Ok(bytes.map(|b| {
        format!(
            "data:{mime};base64,{}",
            base64::engine::general_purpose::STANDARD.encode(b)
        )
    }))
}

#[tauri::command]
pub fn screenshot_status(state: State<'_, AppState>) -> ScreenshotStatus {
    state.screenshots.status()
}

/// Ask the OS for screen-capture permission (macOS); a no-op elsewhere.
#[tauri::command]
pub async fn request_screen_permission() -> bool {
    tauri::async_runtime::spawn_blocking(crate::screen::request_permission)
        .await
        .unwrap_or(false)
}

/// Open the OS privacy page where screen-capture permission is changed.
#[tauri::command]
pub fn open_screen_permission_settings(app: AppHandle) -> Result<(), RpcError> {
    if !cfg!(target_os = "macos") {
        return Err(RpcError::local(
            "not_applicable",
            "This system has no screen-capture permission setting",
        ));
    }
    app.opener()
        .open_url(
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
            None::<&str>,
        )
        .map_err(|_| RpcError::local("open_failed", "System Settings could not be opened"))
}

#[tauri::command]
pub fn reveal_data_dir(app: AppHandle, state: State<'_, AppState>) -> Result<(), RpcError> {
    app.opener()
        .reveal_item_in_dir(&state.data_dir)
        .map_err(|_| RpcError::local("open_failed", "The folder could not be opened"))
}

/// Export to a zip the user names in a save dialog (design §13).
#[tauri::command]
pub async fn export_data(app: AppHandle, state: State<'_, AppState>) -> Result<Value, RpcError> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Export your OmniRecall data")
            .set_file_name("omnirecall-export.zip")
            .add_filter("Zip archive", &["zip"])
            .blocking_save_file()
    })
    .await
    .map_err(|_| RpcError::local("dialog_failed", "The save dialog could not be opened"))?;
    let Some(mut path) = picked.and_then(|p| p.into_path().ok()) else {
        return Ok(json!({ "cancelled": true }));
    };
    if path.extension().and_then(|e| e.to_str()) != Some("zip") {
        path.set_extension("zip");
    }
    state
        .engine
        .request_with_timeout(
            "export.create",
            json!({ "path": path.to_string_lossy() }),
            std::time::Duration::from_secs(1800),
        )
        .await
}

/// Exclude a folder from imports; the folder comes from the OS dialog.
#[tauri::command]
pub async fn add_folder_exclusion(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<Value, RpcError> {
    let picked = tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Choose a folder OmniRecall should never import")
            .blocking_pick_folder()
    })
    .await
    .map_err(|_| RpcError::local("dialog_failed", "The folder dialog could not be opened"))?;
    let Some(path) = picked.and_then(|p| p.into_path().ok()) else {
        return Ok(json!({ "cancelled": true }));
    };
    state
        .engine
        .request(
            "exclusions.add_path",
            json!({ "rule_type": "path", "rule_value": path.to_string_lossy() }),
        )
        .await
}

/// The global pause shortcut and whether the OS accepted it.
#[tauri::command]
pub fn pause_shortcut(state: State<'_, AppState>) -> Value {
    json!({ "shortcut": crate::tray::PAUSE_SHORTCUT, "registered": state.shortcut_registered })
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
            "exclusions.add_path",
            "capture.clipboard",
            "capture.screenshot",
            "capture.screenshot_check",
            "capture.screenshot_skip",
            "anything",
        ] {
            assert!(!ui_may_call(method), "{method} must not be UI-callable");
        }
        assert!(ui_may_call("search"));
    }
}
