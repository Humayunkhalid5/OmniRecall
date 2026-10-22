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

## Screenshot capture (Phase 4)

| Platform | Capture | Permission | Lock / inactivity | Own window and app exclusions | Status |
|---|---|---|---|---|---|
| Windows 10/11 | `xcap` (GDI), every monitor in physical pixels with its scale factor | None needed | Lock: the input desktop cannot be opened. Idle: `GetLastInputInfo` | Foreground window's process | CI build. Remote Desktop sessions and secure desktops (UAC) are not tested; a failed capture is counted as `capture_failed` |
| macOS 13+ | `xcap` (CoreGraphics), every display | Screen Recording. Settings shows a notice with **Ask for permission** and **Open System Settings**; a revoked permission is detected before every capture, and nothing is taken until it is granted again | Lock: `CGSSessionScreenIsLocked`. Idle: `CGEventSourceSecondsSinceLastEventType` | Frontmost application | CI build |
| Linux X11 | `x11rb`: one image per RandR monitor (falls back to the whole screen) | None | Screen saver active counts as locked; idle from the ScreenSaver extension. Lockers that do not use the extension are covered by the inactivity pause | `_NET_ACTIVE_WINDOW`; needs a window manager | Verified on Xvfb (1280x800, no window manager): capture, OCR, search, preview, pause shortcut, idle pause, fail-closed app exclusion, sensitive-text drop, text-only mode, and retention pruning. Without a window manager the front app is unknown, so OmniRecall's own window was captured too; on a desktop with a window manager it is skipped |
| Linux Wayland | Not offered: the portal asks the user on every capture | n/a | n/a | n/a | The switch is disabled with an explanation (OR-015) |

Scaling: frames are kept in physical pixels; the display's scale factor is stored where the OS reports it (Windows, macOS). Multiple displays: each display is captured, deduplicated, and stored separately with its display ID. Not tested: displays added or removed while capturing, mixed-DPI setups, and HDR displays.

## Audio notes (Phase 5)

Audio is imported as files (dialog, drag-and-drop, or folders); OmniRecall does not record from the microphone.

| Format | Extensions | Decoded by the helper | Status |
|---|---|---|---|
| WAV (PCM, ADPCM) | `.wav`, `.wave` | yes | Verified on fixtures |
| MP3 | `.mp3` | yes | Verified on fixtures |
| M4A (AAC or Apple Lossless) | `.m4a` | yes | Verified on fixtures (AAC) |
| AAC (ADTS) | `.aac` | yes | Decoder supports it; no fixture |
| FLAC | `.flac` | yes | Verified on fixtures |
| Ogg Vorbis | `.ogg`, `.oga` | yes | Verified on fixtures |
| AIFF, CAF | `.aif`, `.aiff`, `.caf` | yes | Decoder supports it; no fixture |
| Opus (in Ogg or WebM) | `.ogg`, `.opus` | no | Fails with "This audio encoding is not supported" (fixture) |

| Platform | Decoder helper | whisper.cpp (`pywhispercpp` wheel) | Status |
|---|---|---|---|
| Linux x86_64 | built in CI | yes | Verified with fixtures and a synthetic model. The real `ggml-base` model has not been run here yet |
| Windows x86_64 | builds (pure Rust) | yes | Not run; packaging in Phase 6 |
| macOS arm64 | builds (pure Rust) | yes | Not run; packaging in Phase 6 |
| macOS x86_64 | builds (pure Rust) | no wheel published | Transcription not available until whisper.cpp is built from source (OR-020) |
