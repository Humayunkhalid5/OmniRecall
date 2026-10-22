//! App data location and engine launch resolution.

use std::path::{Path, PathBuf};

use crate::engine::LaunchSpec;

/// Create the data directory tree with owner-only permissions where supported.
pub fn prepare_data_dir(root: &Path) -> std::io::Result<()> {
    for sub in [
        "config",
        "db",
        "vectors",
        "media/screenshots",
        "media/imports",
        "media/audio",
        "media/incoming",
        "models",
        "logs",
        "exports",
    ] {
        std::fs::create_dir_all(root.join(sub))?;
    }
    restrict_permissions(root)
}

#[cfg(unix)]
fn restrict_permissions(root: &Path) -> std::io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))
}

#[cfg(not(unix))]
fn restrict_permissions(_root: &Path) -> std::io::Result<()> {
    // On Windows the per-user AppData ACLs already restrict access to the user.
    Ok(())
}

/// Development builds run the engine from source with `uv`; installed builds
/// run the frozen engine that the installer put in the app's resources
/// (`engine/`, next to its audio decoder and, on Windows and macOS, Tesseract).
pub fn engine_launch(data_dir: &Path, resource_dir: Option<&Path>) -> LaunchSpec {
    let data_arg = data_dir.to_string_lossy().to_string();
    if let Ok(source_dir) = std::env::var("OMNIRECALL_ENGINE_SOURCE") {
        return LaunchSpec {
            program: PathBuf::from("uv"),
            args: vec![
                "run".into(),
                "--project".into(),
                source_dir.clone(),
                "--frozen".into(),
                "omnirecall-engine".into(),
                "--data-dir".into(),
                data_arg,
            ],
            cwd: Some(PathBuf::from(source_dir)),
        };
    }
    LaunchSpec {
        program: bundled_engine(resource_dir),
        args: vec!["--data-dir".into(), data_arg],
        cwd: None,
    }
}

const ENGINE_NAME: &str = if cfg!(windows) {
    "omnirecall-engine.exe"
} else {
    "omnirecall-engine"
};

/// `<resources>/engine/omnirecall-engine`, or next to the app executable when
/// the resource folder is unknown. A missing file shows as `spawn_failed`.
fn bundled_engine(resource_dir: Option<&Path>) -> PathBuf {
    let base = resource_dir.map(Path::to_path_buf).unwrap_or_else(|| {
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(Path::to_path_buf))
            .unwrap_or_else(|| PathBuf::from("."))
    });
    let bundled = base.join("engine").join(ENGINE_NAME);
    if bundled.is_file() {
        bundled
    } else {
        base.join(ENGINE_NAME)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn release_engine_comes_from_the_resource_folder() {
        let dir = tempfile::tempdir().unwrap();
        let engine_dir = dir.path().join("engine");
        std::fs::create_dir_all(&engine_dir).unwrap();
        std::fs::write(engine_dir.join(ENGINE_NAME), b"").unwrap();
        if std::env::var("OMNIRECALL_ENGINE_SOURCE").is_err() {
            let spec = engine_launch(Path::new("/data"), Some(dir.path()));
            assert_eq!(spec.program, engine_dir.join(ENGINE_NAME));
            assert_eq!(
                spec.args,
                vec!["--data-dir".to_string(), "/data".to_string()]
            );
            assert!(spec.cwd.is_none());
        }
        // Without the bundled folder the path still names the engine, so the
        // failure is reported as spawn_failed rather than running something else.
        let empty = tempfile::tempdir().unwrap();
        assert_eq!(
            bundled_engine(Some(empty.path())),
            empty.path().join(ENGINE_NAME)
        );
    }

    #[test]
    fn creates_layout() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("OmniRecall");
        prepare_data_dir(&root).unwrap();
        assert!(root.join("db").is_dir());
        assert!(root.join("media/screenshots").is_dir());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&root).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode, 0o700);
        }
    }
}
