# Troubleshooting

Each section starts with what you see in the app. Codes in `code font` are the diagnostic codes the app shows; they never contain your content.

## Where things are

| | Windows | macOS | Linux |
|---|---|---|---|
| Data folder | `%APPDATA%\app.omnirecall.desktop` | `~/Library/Application Support/app.omnirecall.desktop` | `~/.local/share/app.omnirecall.desktop` |
| Program | `%LOCALAPPDATA%\OmniRecall` | `/Applications/OmniRecall.app` | `/usr/bin/omnirecall`, with the engine in `/usr/lib/OmniRecall/engine` |

Inside the data folder: `db/` (the database: items, text, settings, exclusions), `vectors/` (the search index for meaning, rebuilt from the database when needed), `media/` (stored screenshots, images, and audio), `models/`, `logs/engine.log`, and `exports/`. Settings → Storage → Show data folder opens it.

## "The search engine is not running"

The window shows a diagnostic code and **Restart engine**.

| Code | Meaning | What to do |
|---|---|---|
| `spawn_failed` | The engine program could not be started. | Reinstall OmniRecall. On Linux, check that `/usr/lib/OmniRecall/engine/omnirecall-engine` exists and is executable. |
| `handshake_failed` | The engine started but did not answer its start-up check. | Restart. If it repeats, look at the last lines of `logs/engine.log`. |
| `protocol_mismatch` | The app and engine come from different versions. | Reinstall OmniRecall; do not mix files from two versions. |
| `crash_loop` | The engine stopped several times in a row, so the app stopped restarting it. | Restart once. If it stops again, the log names the failing step (event and error code only). A database that another copy of OmniRecall holds open also ends here: quit the other copy first. |

Your data is not changed by any of these.

## "Your OmniRecall database is damaged"

OmniRecall checks its database every time it starts. If part of the file cannot be read (after a disk error, or power loss while saving), it does not open it, and offers a choice instead. Nothing is changed until you choose.

- **Recover what can be read** copies every readable item, setting, and exclusion into a new database and replaces the damaged file. Afterwards the app lists what happened: how many items were recovered, which lost their text (they show as failed in the Library with "Its text was in a damaged part of the database"), and which imported files will be read again from disk. **Capture is turned off after a recovery**, because some exclusions may have been lost: check Settings → Exclusions before turning it back on.
- **Start over** deletes everything OmniRecall stored and starts empty. Your imported original files are not touched.
- **A backup instead:** if you have a copy of the data folder from before the damage, quit OmniRecall, put `db/omnirecall.sqlite` back from the backup (and delete `omnirecall.sqlite-wal` and `omnirecall.sqlite-shm` next to it), and start again.

Then choose **Restart OmniRecall**.

If the app says **your data was saved by a newer version**, you installed an older OmniRecall over a newer one. Install the newer version again; this version will not change the data.

## Search is keyword-only

- "The search model is not installed": Settings → Local models → Download. Until then, new items wait with `model_missing` and are indexed as soon as the model is installed.
- "The search index is being repaired": OmniRecall found the search index damaged and is rebuilding it from the database. Keyword results still work, and nothing you saved is lost. Results by meaning come back when the rebuild finishes, without a restart.
- Settings → Index maintenance → **Check index** compares the database with the search index. **Rebuild search vectors** rebuilds the index without deleting anything.

## An item failed

The Library shows failed items with the reason. **Retry** runs it again.

| Code | Meaning |
|---|---|
| `source_missing` | The original file was moved or deleted before it was read. |
| `unsupported_format` | Not a format OmniRecall reads (`formats.md`). |
| `limit_exceeded` | Over a limit in Settings → Import and search limits (file size, PDF pages, or recording length). |
| `extraction_empty` | No text was found, for example a scanned PDF without a text layer. |
| `malformed_file`, `binary_content` | The file is damaged, or is not text. |
| `encrypted_file` | Password-protected files are not supported. |
| `ocr_unavailable` | Tesseract is missing. Windows and macOS installers include it; on Linux install `tesseract-ocr` and `tesseract-ocr-eng` (Debian, Ubuntu) or `tesseract` and `tesseract-langpack-eng` (Fedora). The .deb and .rpm packages install them for you. |
| `ocr_failed`, `ocr_timeout` | Text recognition failed, or took longer than 2 minutes for one image. |
| `transcription_model_missing` | Install the speech model in Settings → Local models; audio items are then processed automatically. |
| `audio_decoder_unavailable` | The audio decoder is missing from this installation; reinstall. |
| `unsupported_codec` | The audio encoding is not supported, for example Opus. Convert to MP3, M4A, or FLAC. |
| `recovery_lost_text` | Its text was in a damaged part of the database (see above). Delete the item, or import the file again. |

## Capture does not start or stops

- **Nothing is captured although capture is on:** check the capture indicator. Capture pauses with the shortcut (Ctrl+Alt+Shift+P, Cmd+Option+Shift+P on macOS), while the screen is locked, after 5 minutes without input, and while OmniRecall's own window is in front.
- **App exclusions and an unknown app:** if you have any app exclusion and OmniRecall cannot tell which app is in front (common on Linux without a window manager, and on Wayland), nothing is captured. This is deliberate.
- **macOS screenshots:** OmniRecall needs Screen Recording permission. Settings shows **Ask for permission** and **Open System Settings**. macOS can withdraw the permission; OmniRecall notices before the next capture and waits.
- **Linux Wayland:** screenshot capture is not available (the system asks for permission on every capture). The clipboard may not be readable by background apps; see `support-matrix.md`.

## Uninstalling and removing data

Uninstalling removes the program and keeps the data folder, so a reinstall picks up where you left off.

- **Windows:** Settings → Apps → OmniRecall → Uninstall. The uninstaller has an option to delete the application data as well; leave it unchecked to keep your history.
- **macOS:** move `/Applications/OmniRecall.app` to the Bin.
- **Linux:** `sudo apt remove omni-recall` or `sudo dnf remove omni-recall`.

To remove your data as well, use Settings → Index maintenance → **Delete everything** before uninstalling, which deletes items, index, and media physically. Then delete the data folder from the table above, which also removes settings, exclusions, models, and logs.

## Reporting a problem

Include the app version (Settings), your OS, the diagnostic code, and, if you are comfortable, the last lines of `logs/engine.log`. The log never contains captured text, queries, file names, or app names, but read it before sharing. Never attach your database or media.
