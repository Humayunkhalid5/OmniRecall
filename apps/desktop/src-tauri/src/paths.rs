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

/// Development builds run the engine from source with `uv`; release builds use
/// the bundled sidecar binary next to the executable.
pub fn engine_launch(data_dir: &Path) -> LaunchSpec {
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
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."));
    let name = if cfg!(windows) {
        "omnirecall-engine.exe"
    } else {
        "omnirecall-engine"
    };
    LaunchSpec {
        program: exe_dir.join(name),
        args: vec!["--data-dir".into(), data_arg],
        cwd: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
