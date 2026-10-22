# Support matrix

What each capture feature does on each platform, and how it was verified. "Verified" means run on that platform; "CI build" means it compiles and its unit tests pass there, but the feature was not exercised on a desktop. Nothing here is claimed beyond what the column says (rules.md §1.6).

## Clipboard capture (Phase 3)

| Platform | Change detection | Reading text | Source app (for app exclusions) | Status |
|---|---|---|---|---|
| Windows 10/11 | Clipboard sequence number; text is read only after it changes | `arboard` (Win32) | Foreground window's process name | CI build |
| macOS 13+ | Pasteboard change count; text is read only after it changes. macOS versions with pasteboard privacy prompts ask the user once when OmniRecall first reads a copy | `arboard` (AppKit) | Frontmost application | CI build |
| Linux X11 | None available; the text is read every 0.5 s while capture is on and compared in memory | `arboard` (X11 selections) | `_NET_ACTIVE_WINDOW` process name; unknown without a window manager | Verified on Xvfb (Ubuntu 24.04, no window manager, so the app was unknown) |
| Linux Wayland | As X11, through the `wlr-data-control` protocol where the compositor offers it | `arboard` (`wayland-data-control`) | Usually unknown | Not verified. Compositors without data-control give no clipboard access to background apps (OR-015) |

When the source app is unknown and any app exclusion exists, the copy is dropped (fail closed). While capture is off or paused, the shell does not touch the clipboard at all.

## Capture indicator and pause

| Platform | Tray indicator | Global pause shortcut (Ctrl/Cmd+Alt+Shift+P) |
|---|---|---|
| Windows | Notification area icon | Expected to work; CI build only |
| macOS | Menu bar icon | Expected to work; CI build only |
| Linux | AppIndicator (libayatana-appindicator); needs a StatusNotifier host, which GNOME provides only through an extension | X11: verified on Xvfb. Wayland: global shortcuts are generally unavailable, and Settings says so |

Without a tray host, the window header remains the capture indicator, and closing the window quits the app (capture stops) instead of hiding it.
