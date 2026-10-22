//! OS access for screenshot capture: displays, permission, idle time, and
//! lock state. Each platform uses its supported public APIs only; nothing
//! here bypasses a permission prompt or the lock screen (rules.md §1.4).

use image::RgbaImage;
use serde::Serialize;

/// One display's frame, in physical pixels.
pub struct Shot {
    pub display_id: String,
    pub display_name: Option<String>,
    pub scale: Option<f32>,
    pub image: RgbaImage,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Permission {
    /// The platform has no screen-capture permission (Windows, X11).
    NotRequired,
    Granted,
    /// macOS Screen Recording is off for OmniRecall.
    Denied,
}

/// Why periodic capture cannot run on this platform at all.
pub fn unsupported_reason() -> Option<&'static str> {
    platform::unsupported_reason()
}

pub fn permission() -> Permission {
    platform::permission()
}

/// Ask the OS for permission. Returns whether it is granted now; on macOS the
/// answer usually takes effect only after the app restarts.
pub fn request_permission() -> bool {
    platform::request_permission()
}

/// Seconds since the last keyboard or mouse input, where the OS reports it.
pub fn idle_seconds() -> Option<u64> {
    platform::idle_seconds()
}

/// Whether the session is locked or the screen saver is showing.
pub fn locked() -> bool {
    platform::locked()
}

pub fn capture() -> Result<Vec<Shot>, String> {
    platform::capture()
}

/// Display IDs travel to the engine; keep them to a safe character set.
fn clean_id(raw: &str) -> String {
    let id: String = raw
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || "_.:-".contains(c) {
                c
            } else {
                '_'
            }
        })
        .take(64)
        .collect();
    if id.is_empty() {
        "display".into()
    } else {
        id
    }
}

#[cfg(any(target_os = "windows", target_os = "macos"))]
fn capture_xcap(prefix: &str) -> Result<Vec<Shot>, String> {
    let monitors = xcap::Monitor::all().map_err(|_| "no_displays".to_string())?;
    let mut shots = Vec::new();
    for monitor in monitors {
        let image = monitor
            .capture_image()
            .map_err(|_| "capture_failed".to_string())?;
        let id = monitor.id().map(|id| id.to_string()).unwrap_or_default();
        shots.push(Shot {
            display_id: clean_id(&format!("{prefix}-{id}")),
            display_name: monitor
                .friendly_name()
                .or_else(|_| monitor.name())
                .ok()
                .map(|n| n.chars().take(128).collect()),
            scale: monitor.scale_factor().ok(),
            image,
        });
    }
    if shots.is_empty() {
        return Err("no_displays".into());
    }
    Ok(shots)
}

#[cfg(target_os = "windows")]
mod platform {
    use super::{Permission, Shot};
    use std::ffi::c_void;

    #[repr(C)]
    struct LastInputInfo {
        size: u32,
        time: u32,
    }

    #[link(name = "user32")]
    extern "system" {
        fn GetLastInputInfo(info: *mut LastInputInfo) -> i32;
        fn OpenInputDesktop(flags: u32, inherit: i32, access: u32) -> *mut c_void;
        fn CloseDesktop(desktop: *mut c_void) -> i32;
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn GetTickCount() -> u32;
    }

    const DESKTOP_SWITCHDESKTOP: u32 = 0x0100;

    pub fn unsupported_reason() -> Option<&'static str> {
        None
    }

    pub fn permission() -> Permission {
        Permission::NotRequired
    }

    pub fn request_permission() -> bool {
        true
    }

    pub fn idle_seconds() -> Option<u64> {
        let mut info = LastInputInfo {
            size: std::mem::size_of::<LastInputInfo>() as u32,
            time: 0,
        };
        // SAFETY: `info` is a correctly sized LASTINPUTINFO owned by this frame.
        if unsafe { GetLastInputInfo(&mut info) } == 0 {
            return None;
        }
        // SAFETY: no arguments; reads the system tick counter.
        let now = unsafe { GetTickCount() };
        Some(u64::from(now.wrapping_sub(info.time)) / 1000)
    }

    pub fn locked() -> bool {
        // While the lock screen (or UAC's secure desktop) is up, the input
        // desktop cannot be opened by a normal process.
        // SAFETY: plain Win32 call; a non-null handle is closed below.
        let desktop = unsafe { OpenInputDesktop(0, 0, DESKTOP_SWITCHDESKTOP) };
        if desktop.is_null() {
            return true;
        }
        // SAFETY: `desktop` is the valid handle returned above.
        unsafe { CloseDesktop(desktop) };
        false
    }

    pub fn capture() -> Result<Vec<Shot>, String> {
        super::capture_xcap("win")
    }
}

#[cfg(target_os = "macos")]
mod platform {
    use super::{Permission, Shot};
    use std::ffi::{c_char, c_void};

    type CFTypeRef = *const c_void;

    #[link(name = "CoreGraphics", kind = "framework")]
    extern "C" {
        fn CGPreflightScreenCaptureAccess() -> bool;
        fn CGRequestScreenCaptureAccess() -> bool;
        fn CGEventSourceSecondsSinceLastEventType(state: i32, event_type: u32) -> f64;
        fn CGSessionCopyCurrentDictionary() -> CFTypeRef;
    }

    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        fn CFStringCreateWithCString(
            alloc: CFTypeRef,
            text: *const c_char,
            encoding: u32,
        ) -> CFTypeRef;
        fn CFDictionaryGetValue(dict: CFTypeRef, key: CFTypeRef) -> CFTypeRef;
        fn CFGetTypeID(value: CFTypeRef) -> usize;
        fn CFBooleanGetTypeID() -> usize;
        fn CFBooleanGetValue(value: CFTypeRef) -> bool;
        fn CFRelease(value: CFTypeRef);
    }

    const COMBINED_SESSION_STATE: i32 = 0;
    const ANY_INPUT_EVENT: u32 = u32::MAX;
    const UTF8: u32 = 0x0800_0100;

    pub fn unsupported_reason() -> Option<&'static str> {
        None
    }

    pub fn permission() -> Permission {
        // SAFETY: no arguments; only reads the TCC decision for this app.
        if unsafe { CGPreflightScreenCaptureAccess() } {
            Permission::Granted
        } else {
            Permission::Denied
        }
    }

    pub fn request_permission() -> bool {
        // SAFETY: no arguments; shows the system prompt at most once.
        unsafe { CGRequestScreenCaptureAccess() }
    }

    pub fn idle_seconds() -> Option<u64> {
        // SAFETY: plain value arguments.
        let seconds = unsafe {
            CGEventSourceSecondsSinceLastEventType(COMBINED_SESSION_STATE, ANY_INPUT_EVENT)
        };
        (seconds.is_finite() && seconds >= 0.0).then_some(seconds as u64)
    }

    pub fn locked() -> bool {
        // SAFETY: every CF object created or copied here is released before
        // returning; values read from the dictionary are not retained.
        unsafe {
            let session = CGSessionCopyCurrentDictionary();
            if session.is_null() {
                // No GUI session (for example at the login window).
                return true;
            }
            let key = CFStringCreateWithCString(
                std::ptr::null(),
                c"CGSSessionScreenIsLocked".as_ptr(),
                UTF8,
            );
            let mut locked = false;
            if !key.is_null() {
                let value = CFDictionaryGetValue(session, key);
                if !value.is_null() && CFGetTypeID(value) == CFBooleanGetTypeID() {
                    locked = CFBooleanGetValue(value);
                }
                CFRelease(key);
            }
            CFRelease(session);
            locked
        }
    }

    pub fn capture() -> Result<Vec<Shot>, String> {
        if permission() != Permission::Granted {
            return Err("permission_needed".into());
        }
        super::capture_xcap("mac")
    }
}

#[cfg(all(unix, not(target_os = "macos")))]
mod platform {
    use super::{clean_id, Permission, Shot};
    use image::RgbaImage;
    use x11rb::connection::Connection;
    use x11rb::protocol::randr::ConnectionExt as _;
    use x11rb::protocol::screensaver::ConnectionExt as _;
    use x11rb::protocol::xproto::{ConnectionExt as _, ImageFormat, ImageOrder};

    /// Wayland gives background apps no silent screen capture: the portal asks
    /// the user every time, which periodic capture cannot honour (OR-015).
    pub fn unsupported_reason() -> Option<&'static str> {
        let wayland = std::env::var("XDG_SESSION_TYPE")
            .map(|v| v.eq_ignore_ascii_case("wayland"))
            .unwrap_or(false)
            || (std::env::var_os("WAYLAND_DISPLAY").is_some()
                && std::env::var_os("DISPLAY").is_none());
        if wayland {
            return Some("wayland");
        }
        if std::env::var_os("DISPLAY").is_none() {
            return Some("no_display");
        }
        None
    }

    pub fn permission() -> Permission {
        Permission::NotRequired
    }

    pub fn request_permission() -> bool {
        true
    }

    fn connect() -> Option<(x11rb::rust_connection::RustConnection, usize)> {
        x11rb::connect(None).ok()
    }

    pub fn idle_seconds() -> Option<u64> {
        let (conn, screen) = connect()?;
        let root = conn.setup().roots.get(screen)?.root;
        let info = conn.screensaver_query_info(root).ok()?.reply().ok()?;
        Some(u64::from(info.ms_since_user_input) / 1000)
    }

    pub fn locked() -> bool {
        // A running screen saver (state On) usually means the screen is locked
        // or blanked. Lockers that do not use the extension are covered by the
        // inactivity pause.
        let Some((conn, screen)) = connect() else {
            return false;
        };
        let Some(root) = conn.setup().roots.get(screen).map(|s| s.root) else {
            return false;
        };
        conn.screensaver_query_info(root)
            .ok()
            .and_then(|c| c.reply().ok())
            .map(|info| info.state == 1)
            .unwrap_or(false)
    }

    pub fn capture() -> Result<Vec<Shot>, String> {
        if let Some(reason) = unsupported_reason() {
            return Err(reason.into());
        }
        let (conn, screen_num) = connect().ok_or("no_display")?;
        let setup = conn.setup();
        let screen = setup.roots.get(screen_num).ok_or("no_display")?;
        let root = screen.root;
        let bits_per_pixel = setup
            .pixmap_formats
            .iter()
            .find(|f| f.depth == screen.root_depth)
            .map(|f| f.bits_per_pixel)
            .unwrap_or(0);
        if bits_per_pixel != 32 || setup.image_byte_order != ImageOrder::LSB_FIRST {
            return Err("unsupported_visual".into());
        }
        let monitors = conn
            .randr_get_monitors(root, true)
            .ok()
            .and_then(|c| c.reply().ok())
            .map(|r| r.monitors)
            .unwrap_or_default();
        let regions: Vec<(String, i16, i16, u16, u16)> = if monitors.is_empty() {
            vec![(
                "screen".into(),
                0,
                0,
                screen.width_in_pixels,
                screen.height_in_pixels,
            )]
        } else {
            monitors
                .iter()
                .map(|m| {
                    let name = conn
                        .get_atom_name(m.name)
                        .ok()
                        .and_then(|c| c.reply().ok())
                        .map(|r| String::from_utf8_lossy(&r.name).into_owned())
                        .unwrap_or_else(|| "monitor".into());
                    (name, m.x, m.y, m.width, m.height)
                })
                .collect()
        };
        let mut shots = Vec::new();
        for (name, x, y, width, height) in regions {
            let reply = conn
                .get_image(ImageFormat::Z_PIXMAP, root, x, y, width, height, !0)
                .map_err(|_| "capture_failed")?
                .reply()
                .map_err(|_| "capture_failed")?;
            // 32 bpp little-endian: B, G, R, X per pixel.
            let mut rgba = Vec::with_capacity(reply.data.len());
            for px in reply.data.chunks_exact(4) {
                rgba.extend_from_slice(&[px[2], px[1], px[0], 255]);
            }
            let image = RgbaImage::from_raw(u32::from(width), u32::from(height), rgba)
                .ok_or("capture_failed")?;
            shots.push(Shot {
                display_id: clean_id(&format!("x11-{name}")),
                display_name: Some(name.chars().take(128).collect()),
                scale: None,
                image,
            });
        }
        if shots.is_empty() {
            return Err("no_displays".into());
        }
        Ok(shots)
    }
}

#[cfg(test)]
mod tests {
    use super::clean_id;

    #[test]
    fn display_ids_are_sanitized() {
        assert_eq!(clean_id("x11-HDMI 1/\u{e9}"), "x11-HDMI_1__");
        assert_eq!(clean_id(""), "display");
        assert_eq!(clean_id(&"a".repeat(100)).len(), 64);
    }
}
