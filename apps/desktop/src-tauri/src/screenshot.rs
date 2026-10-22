//! Screenshot watcher. Captures only while the engine reports screenshot
//! capture as active, on the configured interval, and never while the screen
//! is locked, the user is away, OmniRecall itself is in front, or the engine
//! refuses (exclusions, pause, OCR missing). Near-identical frames are dropped
//! here by perceptual hash before anything is written (design §6, D-027).

use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use image::codecs::png::{CompressionType, FilterType, PngEncoder};
use image::{imageops, DynamicImage, ImageEncoder, RgbaImage};
use serde::Serialize;
use serde_json::{json, Value};

use crate::engine::Supervisor;
use crate::screen::{self, Permission};

const TICK: Duration = Duration::from_secs(1);
/// The first frame after capture turns on, so the user sees it working.
const FIRST_DELAY: Duration = Duration::from_secs(3);

/// 64-bit perceptual hash (DCT of a 32x32 grayscale copy, 8x8 low
/// frequencies compared with their median).
pub fn phash(image: &RgbaImage) -> u64 {
    const N: usize = 32;
    let small = imageops::thumbnail(image, N as u32, N as u32);
    let gray = DynamicImage::ImageRgba8(small).into_luma8();
    let pixels: Vec<f64> = gray.pixels().map(|p| f64::from(p.0[0])).collect();
    let cos: Vec<f64> = (0..8 * N)
        .map(|i| {
            let (u, x) = (i / N, i % N);
            ((2 * x + 1) as f64 * u as f64 * std::f64::consts::PI / (2 * N) as f64).cos()
        })
        .collect();
    // Separable DCT-II, keeping only the 8 lowest frequencies on each axis.
    let mut rows = vec![0.0; N * 8];
    for y in 0..N {
        for u in 0..8 {
            rows[y * 8 + u] = (0..N).map(|x| pixels[y * N + x] * cos[u * N + x]).sum();
        }
    }
    let mut coeffs = [0.0f64; 64];
    for v in 0..8 {
        for u in 0..8 {
            coeffs[v * 8 + u] = (0..N).map(|y| rows[y * 8 + u] * cos[v * N + y]).sum();
        }
    }
    let mut sorted: Vec<f64> = coeffs[1..].to_vec();
    sorted.sort_by(|a, b| a.total_cmp(b));
    let median = sorted[sorted.len() / 2];
    coeffs.iter().enumerate().fold(
        0u64,
        |hash, (i, &c)| if c > median { hash | (1 << i) } else { hash },
    )
}

pub fn hamming(a: u64, b: u64) -> u32 {
    (a ^ b).count_ones()
}

/// Remembers the last accepted frame per display.
#[derive(Default)]
pub struct FrameFilter {
    last: HashMap<String, u64>,
}

impl FrameFilter {
    pub fn is_duplicate(&self, display: &str, hash: u64, threshold: u32) -> bool {
        self.last
            .get(display)
            .is_some_and(|&previous| hamming(previous, hash) <= threshold)
    }

    pub fn accept(&mut self, display: &str, hash: u64) {
        self.last.insert(display.to_string(), hash);
    }

    pub fn clear(&mut self) {
        self.last.clear();
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct WatchConfig {
    pub active: bool,
    pub interval: Duration,
    pub idle_pause: Option<Duration>,
    pub threshold: u32,
}

impl Default for WatchConfig {
    fn default() -> Self {
        Self {
            active: false,
            interval: Duration::from_secs(30),
            idle_pause: Some(Duration::from_secs(300)),
            threshold: 5,
        }
    }
}

impl WatchConfig {
    /// Read the watcher settings from the engine's `capture.state`.
    pub fn from_state(state: &Value, active: bool) -> Self {
        let section = &state["screenshot"];
        let defaults = Self::default();
        let secs = |key: &str, default: u64| section[key].as_u64().unwrap_or(default);
        let idle = secs("pause_on_idle_s", 300);
        Self {
            active,
            interval: Duration::from_secs(secs("interval_s", 30).max(5)),
            idle_pause: (idle > 0).then(|| Duration::from_secs(idle)),
            threshold: section["phash_threshold"]
                .as_u64()
                .map(|t| t.min(32) as u32)
                .unwrap_or(defaults.threshold),
        }
    }
}

/// What the settings page shows about screenshot capture on this machine.
#[derive(Clone, Debug, Serialize)]
pub struct ScreenshotStatus {
    pub unsupported_reason: Option<&'static str>,
    pub permission: Permission,
    pub last_error: Option<String>,
    pub last_capture_ms: Option<u64>,
}

#[derive(Clone)]
pub struct ScreenshotWatcher {
    config: Arc<Mutex<WatchConfig>>,
    status: Arc<Mutex<ScreenshotStatus>>,
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

impl ScreenshotWatcher {
    pub fn spawn(engine: Supervisor, incoming: PathBuf) -> Self {
        let watcher = Self {
            config: Arc::new(Mutex::new(WatchConfig::default())),
            status: Arc::new(Mutex::new(ScreenshotStatus {
                unsupported_reason: screen::unsupported_reason(),
                permission: screen::permission(),
                last_error: None,
                last_capture_ms: None,
            })),
        };
        let worker = watcher.clone();
        thread::Builder::new()
            .name("screenshot-watcher".into())
            .spawn(move || worker.run(engine, incoming))
            .expect("screenshot watcher thread");
        watcher
    }

    pub fn configure(&self, config: WatchConfig) {
        *self.config.lock().expect("screenshot config") = config;
    }

    pub fn deactivate(&self) {
        self.config.lock().expect("screenshot config").active = false;
    }

    pub fn status(&self) -> ScreenshotStatus {
        let mut status = self.status.lock().expect("screenshot status").clone();
        status.permission = screen::permission();
        status
    }

    fn set_error(&self, error: Option<String>) {
        self.status.lock().expect("screenshot status").last_error = error;
    }

    fn active(&self) -> bool {
        self.config.lock().expect("screenshot config").active
    }

    fn run(&self, engine: Supervisor, incoming: PathBuf) {
        let mut filter = FrameFilter::default();
        let mut next_due: Option<Instant> = None;
        let mut current = WatchConfig::default();
        loop {
            thread::sleep(TICK);
            let config = self.config.lock().expect("screenshot config").clone();
            if !config.active {
                // Forget everything so re-enabling starts clean.
                filter.clear();
                next_due = None;
                current = config;
                continue;
            }
            if config != current || next_due.is_none() {
                let delay = if current.active {
                    config.interval
                } else {
                    FIRST_DELAY
                };
                next_due = Some(Instant::now() + delay);
                current = config.clone();
            }
            if next_due.is_some_and(|due| Instant::now() < due) {
                continue;
            }
            next_due = Some(Instant::now() + config.interval);
            self.tick(&engine, &incoming, &config, &mut filter);
        }
    }

    fn skip(&self, engine: &Supervisor, reason: &str) {
        let params = json!({ "reason": reason });
        let _ = tauri::async_runtime::block_on(engine.request("capture.screenshot_skip", params));
    }

    fn tick(
        &self,
        engine: &Supervisor,
        incoming: &Path,
        config: &WatchConfig,
        filter: &mut FrameFilter,
    ) {
        if screen::unsupported_reason().is_some() {
            return;
        }
        if screen::locked() {
            return self.skip(engine, "locked");
        }
        if let (Some(limit), Some(idle)) = (config.idle_pause, screen::idle_seconds()) {
            if idle >= limit.as_secs() {
                return self.skip(engine, "idle");
            }
        }
        if screen::permission() == Permission::Denied {
            self.set_error(Some("permission_needed".into()));
            return self.skip(engine, "permission_needed");
        }
        let front = active_win_pos_rs::get_active_window().ok();
        if front
            .as_ref()
            .is_some_and(|w| w.process_id == u64::from(std::process::id()))
        {
            // Never capture OmniRecall's own window (search results, previews).
            return self.skip(engine, "own_app");
        }
        let app = front
            .map(|w| w.app_name)
            .filter(|name| !name.trim().is_empty());
        let check = json!({ "app": app, "app_known": app.is_some() });
        let allowed =
            tauri::async_runtime::block_on(engine.request("capture.screenshot_check", check))
                .ok()
                .and_then(|v| v["allowed"].as_bool())
                .unwrap_or(false);
        // Capture may have been paused while the engine was answering.
        if !allowed || !self.active() {
            return;
        }
        let shots = match screen::capture() {
            Ok(shots) => shots,
            Err(code) => {
                self.set_error(Some(code));
                return self.skip(engine, "capture_failed");
            }
        };
        self.set_error(None);
        for shot in shots {
            let hash = phash(&shot.image);
            if filter.is_duplicate(&shot.display_id, hash, config.threshold) {
                self.skip(engine, "duplicate_image");
                continue;
            }
            if !self.active() {
                return;
            }
            match send_frame(engine, incoming, &shot, hash, app.as_deref()) {
                Ok(outcome) => {
                    if matches!(outcome.as_str(), "captured" | "duplicate_image") {
                        filter.accept(&shot.display_id, hash);
                    }
                    if outcome == "captured" {
                        self.status
                            .lock()
                            .expect("screenshot status")
                            .last_capture_ms = Some(now_ms());
                    }
                }
                Err(code) => self.set_error(Some(code)),
            }
        }
    }
}

fn random_name() -> String {
    let mut bytes = [0u8; 16];
    if getrandom::fill(&mut bytes).is_err() {
        // Uniqueness is all that matters here; the engine validates the name.
        let fallback = now_ms().to_le_bytes();
        bytes[..8].copy_from_slice(&fallback);
        bytes[8..].copy_from_slice(&u64::from(std::process::id()).to_le_bytes());
    }
    let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    format!("shot-{hex}.png")
}

/// Write the frame for the engine: user-only permissions, written under a
/// temporary name and renamed so the engine never sees a partial file.
fn write_png(path: &Path, image: &RgbaImage) -> std::io::Result<()> {
    let rgb = DynamicImage::ImageRgba8(image.clone()).into_rgb8();
    let mut encoded = Vec::new();
    PngEncoder::new_with_quality(&mut encoded, CompressionType::Fast, FilterType::Adaptive)
        .write_image(
            rgb.as_raw(),
            rgb.width(),
            rgb.height(),
            image::ExtendedColorType::Rgb8,
        )
        .map_err(std::io::Error::other)?;
    let partial = path.with_extension("partial");
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let result = options
        .open(&partial)
        .and_then(|mut file| file.write_all(&encoded).and_then(|_| file.sync_all()))
        .and_then(|_| fs::rename(&partial, path));
    if result.is_err() {
        let _ = fs::remove_file(&partial);
    }
    result
}

fn send_frame(
    engine: &Supervisor,
    incoming: &Path,
    shot: &screen::Shot,
    hash: u64,
    app: Option<&str>,
) -> Result<String, String> {
    fs::create_dir_all(incoming).map_err(|_| "write_failed".to_string())?;
    let name = random_name();
    let path = incoming.join(&name);
    write_png(&path, &shot.image).map_err(|_| "write_failed".to_string())?;
    let params = json!({
        "file": name,
        "display_id": shot.display_id,
        "display_name": shot.display_name,
        "app": app,
        "app_known": app.is_some(),
        "phash": format!("{hash:016x}"),
        "width": shot.image.width(),
        "height": shot.image.height(),
        "scale": shot.scale,
    });
    let reply = tauri::async_runtime::block_on(engine.request("capture.screenshot", params));
    // The engine removes the file in every case it answers; this covers the
    // cases where it could not answer.
    let _ = fs::remove_file(&path);
    match reply {
        Ok(value) => Ok(value["outcome"].as_str().unwrap_or("unknown").to_string()),
        Err(_) => Err("engine_unavailable".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::Rgba;

    fn pattern(seed: u32) -> RgbaImage {
        RgbaImage::from_fn(640, 400, |x, y| {
            let v = ((x / 40 + y / 40 + seed) % 2 * 200 + 20) as u8;
            Rgba([v, v, v, 255])
        })
    }

    /// Real screenshots of text from the OCR fixtures.
    fn fixture(name: &str) -> RgbaImage {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../services/local-engine/tests/fixtures/images")
            .join(format!("{name}.png"));
        image::open(path).expect("fixture image").into_rgba8()
    }

    #[test]
    fn identical_frames_hash_identically() {
        let shot = fixture("chat_message");
        assert_eq!(phash(&shot), phash(&shot.clone()));
    }

    #[test]
    fn a_small_change_stays_within_the_threshold() {
        for name in ["chat_message", "terminal_error", "slide_photosynthesis"] {
            let base = fixture(name);
            let mut cursor = base.clone();
            // A text cursor: 2 x 18 px.
            for x in 100..102 {
                for y in 40..58 {
                    cursor.put_pixel(x, y, Rgba([0, 0, 0, 255]));
                }
            }
            let distance = hamming(phash(&base), phash(&cursor));
            assert!(distance <= 5, "{name}: distance {distance}");
        }
    }

    #[test]
    fn a_different_screen_is_not_a_duplicate() {
        let names = [
            "chat_message",
            "terminal_error",
            "slide_photosynthesis",
            "small_ui_text",
        ];
        for (i, a) in names.iter().enumerate() {
            for b in &names[i + 1..] {
                let distance = hamming(phash(&fixture(a)), phash(&fixture(b)));
                assert!(distance > 5, "{a} vs {b}: distance {distance}");
            }
        }
    }

    #[test]
    fn filter_is_per_display_and_clears() {
        let mut filter = FrameFilter::default();
        assert!(!filter.is_duplicate("a", 0b1011, 5));
        filter.accept("a", 0b1011);
        assert!(filter.is_duplicate("a", 0b1111, 5));
        assert!(!filter.is_duplicate("b", 0b1011, 5));
        assert!(!filter.is_duplicate("a", u64::MAX, 5));
        filter.clear();
        assert!(!filter.is_duplicate("a", 0b1011, 5));
    }

    #[test]
    fn config_follows_engine_state_with_safe_bounds() {
        let state =
            json!({"screenshot": {"interval_s": 2, "pause_on_idle_s": 0, "phash_threshold": 99}});
        let config = WatchConfig::from_state(&state, true);
        assert_eq!(config.interval, Duration::from_secs(5));
        assert_eq!(config.idle_pause, None);
        assert_eq!(config.threshold, 32);
        let defaults = WatchConfig::from_state(&json!({}), false);
        assert_eq!(defaults, WatchConfig::default());
    }

    #[test]
    fn frames_are_written_atomically_with_private_permissions() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join(random_name());
        write_png(&path, &pattern(0)).unwrap();
        let bytes = fs::read(&path).unwrap();
        assert!(bytes.starts_with(b"\x89PNG\r\n\x1a\n"));
        assert!(!path.with_extension("partial").exists());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(&path).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, 0o600);
        }
        // Names match what the engine accepts: shot-<32 hex>.png
        let name = random_name();
        assert_eq!(name.len(), 5 + 32 + 4);
        assert!(name[5..37].chars().all(|c| c.is_ascii_hexdigit()));
    }
}
