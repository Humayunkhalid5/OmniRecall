"""App-owned media paths (design.md §4, §12)."""

from __future__ import annotations

from pathlib import Path

from omnirecall import logs

# Transient payloads waiting for the pipeline; never exported or counted as kept media.
TRANSIENT_DIR = "incoming"


def owned_media_path(media_root: Path, media_uri: str | None) -> Path | None:
    """Resolve a stored media URI, refusing anything outside the media root."""
    if not media_uri:
        return None
    root = media_root.resolve()
    path = (root / media_uri).resolve()
    if not path.is_relative_to(root):
        logs.error("media_path_outside_root", reason="refused")
        return None
    return path


def media_files(path: Path) -> list[Path]:
    """The media file and its thumbnail, if any."""
    return [path, path.with_name(path.stem + ".thumb.webp")]


def remove_media(path: Path) -> None:
    for candidate in media_files(path):
        candidate.unlink(missing_ok=True)


def media_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in media_files(path) if p.is_file())
