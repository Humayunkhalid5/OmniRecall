# Privacy statement

OmniRecall helps you find things you have already seen, copied, saved, or recorded. It does this entirely on your computer.

## What OmniRecall collects

Only what you choose:

- **Files you import** (documents, images, audio): their text is read and indexed. OmniRecall keeps its own copy of the text, and for images and audio a copy of the file, in its data folder. Your original files are never changed, moved, or deleted.
- **Clipboard** (off until you turn it on): text you copy while capture is on.
- **Screenshots** (off until you turn it on): the text on your screen every 30 seconds while it changes. Screenshot images are kept for 7 days and then deleted, leaving the text. In text-only mode no image is kept at all.

The capture indicator in the window and in the menu bar or notification area shows when capture is on. One shortcut (Ctrl+Alt+Shift+P, or Cmd+Option+Shift+P on macOS) pauses all capture. Capture also stops whenever the app or its engine is not running.

Before anything is captured, OmniRecall checks your exclusions: apps (for example your password manager) and text patterns you never want kept. If you have app exclusions and OmniRecall cannot tell which app is in front, it does not capture. Copies and screens that look like passwords, keys, or tokens are dropped by default. This detection is best effort; it cannot recognize every secret, so add exclusions for sensitive apps.

OmniRecall does not record from your microphone.

## What leaves your computer

Nothing you capture or import, and nothing you search for. OmniRecall has no account, no cloud service, no analytics, and no crash reporting. Its engine does not open any network port.

The only network request OmniRecall makes is a model download that you start yourself in Settings: the search model (about 83 MB, from the URL shown before download) and the optional speech model (about 148 MB). Each file is checked against a published checksum before it is used. After that, OmniRecall works with no network connection.

## Where your data is

| System | Data folder |
|---|---|
| Windows | `%APPDATA%\app.omnirecall.desktop` |
| macOS | `~/Library/Application Support/app.omnirecall.desktop` |
| Linux | `~/.local/share/app.omnirecall.desktop` |

Settings → Storage shows the exact folder and how much space it uses, with a button that opens it. On macOS and Linux only your user account can open it.

**The data folder is not encrypted by OmniRecall.** Anyone who can read your files can read it. Turn on your system's disk encryption (BitLocker, FileVault, or LUKS) to protect it on a lost or stolen computer.

Logs in the data folder record what the app did (for example "item indexed" or "capture paused"), with counts and error codes. They never contain captured text, search queries, file names, app names, or your exclusions.

## Deleting your data

- **One item:** open it and choose Delete, then Delete permanently. Its text, its index entries, and its stored image or audio are removed from disk before the app reports it deleted, including the database's journal and old index versions.
- **Everything:** Settings → Index maintenance → Delete everything removes every item, the whole search index, and all stored media. Your settings and exclusions stay.
- **Export first:** Settings → Your data → Export writes your items and their text to a zip file you choose.
- **Uninstalling** removes the program but leaves the data folder, so reinstalling keeps your history. To remove everything, use Delete everything before uninstalling, or delete the data folder above afterwards (see `troubleshooting.md`).

Deletion cannot reach copies outside OmniRecall's control, such as backups or a synced home folder that includes the data folder.

## Changes

This statement describes version 0.1. Any change to what OmniRecall collects or sends will be listed in the changelog and in this file before it ships.
