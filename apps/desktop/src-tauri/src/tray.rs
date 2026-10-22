//! Capture indicator: a tray icon that is present while the app runs and
//! shows whether capture is on, paused, or off, with one-click pause.

use serde_json::Value;
use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{TrayIcon, TrayIconBuilder};
use tauri::{AppHandle, Manager, Wry};

pub const PAUSE_SHORTCUT: &str = "CommandOrControl+Alt+Shift+P";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Indicator {
    Off,
    On,
    Paused,
}

/// Summary of the engine's `capture.state` for the indicator and watcher.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CaptureSummary {
    pub indicator: Indicator,
    pub clipboard_active: bool,
    pub screenshot_active: bool,
    pub any_enabled: bool,
    pub paused: bool,
}

impl CaptureSummary {
    pub const OFF: Self = Self {
        indicator: Indicator::Off,
        clipboard_active: false,
        screenshot_active: false,
        any_enabled: false,
        paused: false,
    };

    pub fn from_state(state: &Value) -> Self {
        let sources = state["sources"].as_object();
        let flag = |name: &str, key: &str| {
            sources
                .and_then(|s| s.get(name))
                .and_then(|s| s.get(key))
                .and_then(Value::as_bool)
                .unwrap_or(false)
        };
        let names = ["clipboard", "screenshot"];
        let any_enabled = names.iter().any(|n| flag(n, "enabled"));
        let any_active = names.iter().any(|n| flag(n, "active"));
        let paused = state["paused"].as_bool().unwrap_or(false);
        let indicator = if any_active {
            Indicator::On
        } else if any_enabled {
            Indicator::Paused
        } else {
            Indicator::Off
        };
        Self {
            indicator,
            clipboard_active: flag("clipboard", "active"),
            screenshot_active: flag("screenshot", "active"),
            any_enabled,
            paused,
        }
    }

    pub fn status_text(&self) -> &'static str {
        match self.indicator {
            Indicator::On => "Capture is on",
            Indicator::Paused => "Capture is paused",
            Indicator::Off => "Capture is off",
        }
    }
}

pub struct Tray {
    icon: TrayIcon<Wry>,
    status: MenuItem<Wry>,
    pause: MenuItem<Wry>,
}

fn image(indicator: Indicator) -> Image<'static> {
    let bytes: &'static [u8] = match indicator {
        Indicator::On => include_bytes!("../icons/tray-on.png"),
        Indicator::Paused => include_bytes!("../icons/tray-paused.png"),
        Indicator::Off => include_bytes!("../icons/tray-off.png"),
    };
    Image::from_bytes(bytes).expect("bundled tray icon")
}

impl Tray {
    pub fn build(app: &AppHandle) -> tauri::Result<Self> {
        let status = MenuItem::with_id(app, "status", "Capture is off", false, None::<&str>)?;
        let pause = MenuItem::with_id(
            app,
            "pause",
            "Pause all capture",
            true,
            Some(PAUSE_SHORTCUT),
        )?;
        let open = MenuItem::with_id(app, "open", "Open OmniRecall", true, None::<&str>)?;
        let quit = MenuItem::with_id(app, "quit", "Quit OmniRecall", true, None::<&str>)?;
        let separator = PredefinedMenuItem::separator(app)?;
        let menu = Menu::with_items(app, &[&status, &separator, &pause, &open, &quit])?;
        let icon = TrayIconBuilder::with_id("capture")
            .icon(image(Indicator::Off))
            .tooltip("OmniRecall: capture is off")
            .menu(&menu)
            .show_menu_on_left_click(true)
            .on_menu_event(|app, event| match event.id.as_ref() {
                "pause" => crate::toggle_pause(app),
                "open" => crate::show_main_window(app),
                "quit" => crate::quit(app),
                _ => {}
            })
            .build(app)?;
        Ok(Self {
            icon,
            status,
            pause,
        })
    }

    pub fn update(&self, summary: &CaptureSummary) {
        let _ = self.icon.set_icon(Some(image(summary.indicator)));
        let _ = self.icon.set_tooltip(Some(format!(
            "OmniRecall: {}",
            summary.status_text().to_lowercase()
        )));
        let _ = self.status.set_text(summary.status_text());
        let _ = self.pause.set_text(if summary.paused {
            "Resume capture"
        } else {
            "Pause all capture"
        });
        // Pausing means nothing while every source is off.
        let _ = self
            .pause
            .set_enabled(summary.any_enabled || summary.paused);
    }
}

/// Look up the tray stored in app state, if it was created.
pub fn update(app: &AppHandle, summary: &CaptureSummary) {
    if let Some(tray) = app.try_state::<Tray>() {
        tray.update(summary);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn state(enabled: bool, source_paused: bool, paused: bool) -> Value {
        let active = enabled && !source_paused && !paused;
        json!({
            "paused": paused,
            "sources": {
                "clipboard": {"enabled": enabled, "paused": source_paused, "active": active},
                "screenshot": {"enabled": false, "paused": false, "active": false}
            }
        })
    }

    #[test]
    fn indicator_follows_engine_state() {
        assert_eq!(
            CaptureSummary::from_state(&state(false, false, false)),
            CaptureSummary::OFF
        );
        let on = CaptureSummary::from_state(&state(true, false, false));
        assert_eq!(on.indicator, Indicator::On);
        assert!(on.clipboard_active);
        let paused = CaptureSummary::from_state(&state(true, false, true));
        assert_eq!(paused.indicator, Indicator::Paused);
        assert!(!paused.clipboard_active && paused.paused);
        let source_paused = CaptureSummary::from_state(&state(true, true, false));
        assert_eq!(source_paused.indicator, Indicator::Paused);
        assert!(!source_paused.clipboard_active);
    }

    #[test]
    fn malformed_state_means_off() {
        assert_eq!(CaptureSummary::from_state(&json!({})), CaptureSummary::OFF);
        assert_eq!(
            CaptureSummary::from_state(&json!(null)),
            CaptureSummary::OFF
        );
    }
}
