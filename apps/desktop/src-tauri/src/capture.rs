//! Clipboard watcher. Reads the clipboard only while the engine reports
//! clipboard capture as active (enabled, not paused); otherwise it does not
//! touch the clipboard at all. New text goes to the engine, which applies the
//! size limit, exclusions, and secret filter before anything is stored.

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use serde_json::json;

use crate::engine::Supervisor;

const POLL: Duration = Duration::from_millis(500);
/// Copies above this size are never sent to the engine; the engine's own
/// clipboard limit is lower (at most 4 MiB, design §11 default 100 KB).
const MAX_SEND_BYTES: usize = 4 * 1024 * 1024;

/// Decides which clipboard reads are new copies worth sending. Kept free of
/// OS calls so the rules can be tested.
#[derive(Default)]
pub struct ChangeFilter {
    primed: bool,
    last_token: Option<u64>,
    last_hash: Option<u64>,
}

pub enum Observation {
    /// Capture is off: forget everything so re-enabling starts clean.
    Inactive,
    /// The change token did not move; nothing was read.
    Unchanged,
    /// Capture just became active; the current clipboard is a baseline, not a copy.
    Baseline,
    /// The same text as last time.
    Repeat,
    New(String),
}

impl ChangeFilter {
    /// `token` is the OS change counter where one exists; `read` reads the
    /// clipboard text and is called only when a change is possible.
    pub fn observe(
        &mut self,
        active: bool,
        token: Option<u64>,
        read: impl FnOnce() -> Option<String>,
    ) -> Observation {
        if !active {
            *self = Self::default();
            return Observation::Inactive;
        }
        if self.primed && token.is_some() && token == self.last_token {
            return Observation::Unchanged;
        }
        self.last_token = token;
        let text = read();
        let hash = text.as_deref().map(hash_text);
        if !self.primed {
            self.primed = true;
            self.last_hash = hash;
            return Observation::Baseline;
        }
        match text {
            Some(text) if hash != self.last_hash => {
                self.last_hash = hash;
                Observation::New(text)
            }
            _ => {
                self.last_hash = hash.or(self.last_hash);
                Observation::Repeat
            }
        }
    }
}

fn hash_text(text: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    text.hash(&mut hasher);
    hasher.finish()
}

#[cfg(target_os = "windows")]
fn change_token() -> Option<u64> {
    #[link(name = "user32")]
    extern "system" {
        fn GetClipboardSequenceNumber() -> u32;
    }
    // SAFETY: takes no arguments and only reads a counter.
    Some(u64::from(unsafe { GetClipboardSequenceNumber() }))
}

#[cfg(target_os = "macos")]
fn change_token() -> Option<u64> {
    let board = objc2_app_kit::NSPasteboard::generalPasteboard();
    Some(board.changeCount() as u64)
}

/// X11 and Wayland expose no change counter, so the text is compared instead.
#[cfg(not(any(target_os = "windows", target_os = "macos")))]
fn change_token() -> Option<u64> {
    None
}

/// The application in front when the copy was seen. Best effort: it is the
/// focused app, which is normally the one the user copied from.
fn frontmost_app() -> Option<String> {
    active_win_pos_rs::get_active_window()
        .ok()
        .map(|w| w.app_name)
        .filter(|name| !name.trim().is_empty())
}

#[derive(Clone)]
pub struct ClipboardWatcher {
    active: Arc<AtomicBool>,
}

impl ClipboardWatcher {
    pub fn spawn(engine: Supervisor) -> Self {
        let active = Arc::new(AtomicBool::new(false));
        let flag = active.clone();
        thread::Builder::new()
            .name("clipboard-watcher".into())
            .spawn(move || run(flag, engine))
            .expect("clipboard watcher thread");
        Self { active }
    }

    pub fn set_active(&self, active: bool) {
        self.active.store(active, Ordering::SeqCst);
    }

    pub fn is_active(&self) -> bool {
        self.active.load(Ordering::SeqCst)
    }
}

fn run(active: Arc<AtomicBool>, engine: Supervisor) {
    let mut filter = ChangeFilter::default();
    let mut clipboard: Option<arboard::Clipboard> = None;
    loop {
        thread::sleep(POLL);
        let is_active = active.load(Ordering::SeqCst);
        if !is_active {
            // Release the OS clipboard handle while capture is off.
            clipboard = None;
        }
        let observation = filter.observe(is_active, change_token(), || {
            if clipboard.is_none() {
                clipboard = arboard::Clipboard::new().ok();
            }
            clipboard.as_mut().and_then(|c| c.get_text().ok())
        });
        let Observation::New(text) = observation else {
            continue;
        };
        // Capture may have been paused while the clipboard was being read.
        if !active.load(Ordering::SeqCst) || text.len() > MAX_SEND_BYTES || text.trim().is_empty() {
            continue;
        }
        let app = frontmost_app();
        let params = json!({ "text": text, "app": app, "app_known": app.is_some() });
        // Sequential sends keep copies in order and apply backpressure.
        let _ = tauri::async_runtime::block_on(engine.request("capture.clipboard", params));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn read(text: &str) -> impl FnOnce() -> Option<String> + '_ {
        move || Some(text.to_string())
    }

    #[test]
    fn inactive_never_reads() {
        let mut filter = ChangeFilter::default();
        let observed = filter.observe(false, Some(1), || panic!("read while inactive"));
        assert!(matches!(observed, Observation::Inactive));
    }

    #[test]
    fn existing_clipboard_is_a_baseline_not_a_capture() {
        let mut filter = ChangeFilter::default();
        assert!(matches!(
            filter.observe(true, None, read("old")),
            Observation::Baseline
        ));
        assert!(matches!(
            filter.observe(true, None, read("old")),
            Observation::Repeat
        ));
        assert!(
            matches!(filter.observe(true, None, read("new")), Observation::New(t) if t == "new")
        );
    }

    #[test]
    fn unchanged_token_skips_the_read() {
        let mut filter = ChangeFilter::default();
        filter.observe(true, Some(7), read("a"));
        let observed = filter.observe(true, Some(7), || panic!("read without a change"));
        assert!(matches!(observed, Observation::Unchanged));
        assert!(matches!(
            filter.observe(true, Some(8), read("b")),
            Observation::New(_)
        ));
    }

    #[test]
    fn re_enabling_starts_from_a_new_baseline() {
        let mut filter = ChangeFilter::default();
        filter.observe(true, None, read("a"));
        filter.observe(false, None, read("ignored"));
        // Copied while off: becomes the baseline, never captured.
        assert!(matches!(
            filter.observe(true, None, read("copied while off")),
            Observation::Baseline
        ));
    }

    #[test]
    fn non_text_clipboard_is_ignored() {
        let mut filter = ChangeFilter::default();
        filter.observe(true, Some(1), read("a"));
        assert!(matches!(
            filter.observe(true, Some(2), || None),
            Observation::Repeat
        ));
        // Copying the same text again after an image is still a repeat.
        assert!(matches!(
            filter.observe(true, Some(3), read("a")),
            Observation::Repeat
        ));
    }
}
