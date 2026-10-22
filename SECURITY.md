# Security and privacy reports

OmniRecall keeps a searchable record of what its users copy, see, and import, so a weakness in it can expose private data. Please report anything like that privately.

## How to report

Use **Report a vulnerability** on the repository's Security tab (GitHub private vulnerability reporting). Please do not open a public issue, and do not include anyone's real captured content: describe the problem with made-up text.

Examples of what to report this way:
- Content (captured text, queries, file names, app names, exclusions) reaching a log, an error message, the problem report, or any file outside the data folder.
- Anything that sends data off the computer, or an engine that listens on a network port.
- Capture that happens while it is off, paused, excluded, or while the indicator does not show it.
- Deleted items that can still be recovered from the data folder.
- Ways for the window's web content to reach the engine or the file system beyond the documented commands (`apps/desktop/src-tauri/src/commands.rs`).

What is known and documented is not a vulnerability by itself: the data folder is not encrypted by OmniRecall, secret detection is best-effort, and installers are not code-signed yet (`docs/threat-model.md`, `CHANGELOG.md`).

## What happens next

This is a beta maintained by a small team. We aim to acknowledge a report within 7 days, and to fix data-exposure problems before any other work. Fixes are released as a new beta with a changelog entry that credits the reporter unless they prefer otherwise.

## Supported versions

Only the latest beta release receives fixes.
