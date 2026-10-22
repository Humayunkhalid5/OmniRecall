"""Screenshot capture: admission before capture, intake, and the post-OCR review.

The shell takes screenshots (it owns OS permissions and the frontmost app,
D-027). It asks ``check`` before every capture so an excluded app's screen is
never captured at all, drops near-identical frames itself by perceptual hash,
and hands each remaining frame over as a PNG in ``media/incoming``. ``submit``
re-checks everything, then moves the file into app-owned media and queues it.

After OCR, ``review`` drops frames with no text, excluded or sensitive text,
or the same text as the previous accepted frame on that display. A dropped
frame's image and row are removed; only per-session counts and a log line
with the reason remain (D-028).
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omnirecall import logs
from omnirecall.capture import sensitive
from omnirecall.capture.exclusions import ExclusionService
from omnirecall.capture.state import CaptureState
from omnirecall.errors import ValidationError
from omnirecall.ids import sha256_file, sha256_text, utc_now
from omnirecall.settings import Settings
from omnirecall.storage.media import TRANSIENT_DIR
from omnirecall.storage.repository import Item, NewItem, Repository

SOURCE = "screenshot"
SCREENSHOT_DIR = "screenshots"
# Names the shell may use for frames waiting in media/incoming.
INCOMING_NAME = re.compile(r"^shot-[0-9a-f]{32}\.png$")
# A lossless PNG of an 8K display is well under this.
MAX_FRAME_BYTES = 128 * 1024 * 1024
# Reasons the shell reports for frames it did not capture or did not send.
SHELL_SKIP_REASONS = frozenset(
    {"duplicate_image", "idle", "locked", "permission_needed", "capture_failed", "own_app"}
)
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class Frame:
    file: str
    display_id: str
    display_name: str | None
    app: str | None
    app_known: bool
    phash: str | None
    width: int
    height: int
    scale: float | None


class ScreenshotCapture:
    def __init__(
        self,
        state: CaptureState,
        exclusions: ExclusionService,
        repo: Repository,
        media_root: Path,
        settings: Callable[[], Settings],
        wake: Callable[[], None],
        ocr_available: Callable[[], bool],
    ) -> None:
        self.state = state
        self.exclusions = exclusions
        self.repo = repo
        self.media_root = media_root.resolve()
        self._settings = settings
        self._wake = wake
        self._ocr_available = ocr_available
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        # display id -> (item id, OCR text hash) of the last accepted frame
        self._last_text: dict[str, tuple[str, str]] = {}

    # ---- counts ------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def record(self, outcome: str) -> dict[str, Any]:
        with self._lock:
            self._counts[outcome] += 1
        logs.info("screenshot_capture", status=outcome)
        return {"outcome": outcome}

    def skip(self, reason: str) -> dict[str, Any]:
        if reason not in SHELL_SKIP_REASONS:
            raise ValidationError("Unknown skip reason", "reason")
        return self.record(reason)

    # ---- admission ---------------------------------------------------------

    def _refusal(self, app: str | None, app_known: bool) -> str | None:
        if not self.state.is_active(SOURCE):
            return "inactive"
        if not self._ocr_available():
            return "ocr_unavailable"
        rules = self.exclusions.rules()
        if rules.apps and not app_known:
            return "app_unknown"  # an app exclusion cannot be honoured: fail closed
        if rules.app_excluded(app):
            return "excluded_app"
        if self.repo.active_job_count() >= self._settings().queue_capacity:
            return "queue_full"
        return None

    def check(self, app: str | None, app_known: bool) -> dict[str, Any]:
        """May the shell capture the screen now? Refusals are counted."""
        reason = self._refusal(app, app_known)
        if reason is None:
            return {"allowed": True}
        if reason != "inactive":
            self.record(reason)
        return {"allowed": False, "reason": reason}

    # ---- intake ------------------------------------------------------------

    def _incoming(self, name: str) -> Path:
        if not INCOMING_NAME.match(name):
            raise ValidationError("Invalid frame name", "file")
        incoming = (self.media_root / TRANSIENT_DIR).resolve()
        path = incoming / name
        if path.is_symlink() or not path.is_file() or path.parent.resolve() != incoming:
            raise ValidationError("The frame file is missing", "file")
        return path

    def submit(self, frame: Frame) -> dict[str, Any]:
        path = self._incoming(frame.file)
        try:
            return self._submit(frame, path)
        finally:
            path.unlink(missing_ok=True)

    def _submit(self, frame: Frame, path: Path) -> dict[str, Any]:
        reason = self._refusal(frame.app, frame.app_known)
        if reason is not None:
            return self.record(reason)
        size = path.stat().st_size
        if size > MAX_FRAME_BYTES:
            return self.record("too_large")
        with path.open("rb") as handle:
            if handle.read(8) != _PNG_MAGIC:
                raise ValidationError("The frame is not a PNG image", "file")
        content_hash = sha256_file(path)
        if self.repo.find_by_hash(SOURCE, content_hash) is not None:
            return self.record("duplicate_image")
        captured_at = utc_now()
        relative = f"{SCREENSHOT_DIR}/{captured_at[:4]}/{captured_at[5:7]}/{content_hash}.png"
        target = self.media_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
        label = frame.app or "Screenshot"
        metadata: dict[str, Any] = {
            "mime": "image/png",
            "bytes": size,
            "width": frame.width,
            "height": frame.height,
            "display_id": frame.display_id,
        }
        optional = {
            "display_name": frame.display_name,
            "app": frame.app,
            "phash": frame.phash,
            "scale": frame.scale,
        }
        metadata |= {k: v for k, v in optional.items() if v is not None}
        try:
            item, created = self.repo.create_item(
                NewItem(
                    source_type=SOURCE,
                    captured_at=captured_at,
                    content_hash=content_hash,
                    source_label=label[:200],
                    media_uri=relative,
                    metadata=metadata,
                )
            )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        if not created:
            return self.record("duplicate_image")
        self._wake()
        return self.record("captured") | {"item_id": item.id}

    # ---- post-OCR review ---------------------------------------------------

    def review(self, item: Item, text: str) -> str | None:
        """Why this frame should be dropped after OCR, or None to index it."""
        if not text.strip():
            return "no_text"
        rules = self.exclusions.rules()
        if rules.pattern_excluded(text):
            return "excluded_pattern"
        if self._settings().screenshot_detect_secrets and sensitive.detect(text) is not None:
            return "sensitive"
        display = str(item.metadata.get("display_id", ""))
        text_hash = sha256_text(text)
        with self._lock:
            previous = self._last_text.get(display)
            if previous is None:
                previous = self.repo.latest_screenshot_text(display, exclude_item=item.id)
            if previous is not None and previous[1] == text_hash and previous[0] != item.id:
                self._last_text[display] = previous
                same_as = previous[0]
            else:
                self._last_text[display] = (item.id, text_hash)
                same_as = None
        if same_as is not None:
            # The screen still shows what that frame already holds.
            try:
                self.repo.set_metadata(same_as, {"last_seen_at": item.captured_at})
            except Exception:  # noqa: BLE001 - the earlier frame may have been deleted
                logs.warning("screenshot_last_seen_failed", item_id=same_as)
            return "same_text"
        self.repo.set_metadata(item.id, {"text_hash": text_hash})
        return None

    def forget(self, item_id: str) -> None:
        """Drop the remembered last frame if it was this item (deleted or failed)."""
        with self._lock:
            for display, (last_id, _) in list(self._last_text.items()):
                if last_id == item_id:
                    del self._last_text[display]
