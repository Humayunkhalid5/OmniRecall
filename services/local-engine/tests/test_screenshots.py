"""Screenshot capture (Phase 4): admission, intake, post-OCR review, text-only mode.

OCR is faked here so the tests are fast and exact; tests/test_ocr.py runs the
real Tesseract adapter.
"""

from __future__ import annotations

import io
import uuid

import pytest
from engine_support import Recorder, wait_until
from PIL import Image
from support import HashEmbedder

from omnirecall import logs
from omnirecall.app import Engine
from omnirecall.errors import ValidationError
from omnirecall.extraction.ocr import OcrResult

MARKER = "pelican-umbrella-5521 quarterly roadmap for the observatory"


class FakeOcr:
    """Returns the text registered for an image's top-left pixel colour."""

    name = "fake"

    def __init__(self) -> None:
        self.texts: dict[tuple[int, int, int], str] = {}
        self.installed = True
        self.calls = 0

    def available(self) -> bool:
        return self.installed

    def version(self) -> str | None:
        return "1.0" if self.installed else None

    def recognize(self, image: Image.Image) -> OcrResult:
        self.calls += 1
        pixel = image.convert("RGB").getpixel((0, 0))
        assert isinstance(pixel, tuple)
        return OcrResult(self.texts.get(pixel[:3], ""), {"ocr_engine": self.name})


@pytest.fixture
def ocr():
    return FakeOcr()


@pytest.fixture
def engine(tmp_path, ocr):
    eng = Engine(tmp_path / "data", None, Recorder(), embedder=HashEmbedder(), ocr=ocr)
    yield eng
    eng.close()


def enable(engine):
    engine.capture_set_source({"source_type": "screenshot", "enabled": True})


_colours = iter(range(1, 250))


def frame(engine, ocr, text: str | None, colour=None, **extra):
    """Write a PNG into media/incoming as the shell would, and describe it."""
    colour = colour or (next(_colours), 40, 80)
    if text is not None:
        ocr.texts[colour] = text
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), colour).save(buffer, "PNG")
    name = f"shot-{uuid.uuid4().hex}.png"
    (engine.media_root / "incoming" / name).write_bytes(buffer.getvalue())
    params = {
        "file": name,
        "display_id": "display-1",
        "display_name": "Built-in display",
        "app": "Editor",
        "app_known": True,
        "phash": "00ff00ff00ff00ff",
        "width": 64,
        "height": 48,
        "scale": 2.0,
    } | extra
    return params


def submit(engine, ocr, text, **extra):
    return engine.capture_screenshot(frame(engine, ocr, text, **extra))


def items(engine) -> list[dict]:
    rows = engine.db.conn.execute("SELECT id, status, media_uri FROM items").fetchall()
    return [dict(r) for r in rows]


def media_files(engine) -> list[str]:
    return sorted(
        str(p.relative_to(engine.media_root)) for p in engine.media_root.rglob("*") if p.is_file()
    )


def wait_indexed(engine, item_id):
    wait_until(lambda: engine.repo.get_item(item_id).status == "indexed")


def wait_gone(engine, item_id):
    wait_until(
        lambda: (
            engine.db.conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone()
            is None
        )
    )


def test_screenshot_source_starts_off_and_refuses(engine, ocr):
    assert engine.capture_screenshot_check({"app": "Editor", "app_known": True}) == {
        "allowed": False,
        "reason": "inactive",
    }
    params = frame(engine, ocr, MARKER)
    assert engine.capture_screenshot(params) == {"outcome": "inactive"}
    assert items(engine) == []
    assert media_files(engine) == []  # the incoming frame was removed


def test_pause_refuses_capture(engine, ocr):
    enable(engine)
    engine.capture_pause({"paused": True})
    assert engine.capture_screenshot_check({"app_known": False})["allowed"] is False
    assert submit(engine, ocr, MARKER) == {"outcome": "inactive"}
    engine.capture_pause({"paused": False})
    engine.capture_set_source({"source_type": "screenshot", "paused": True})
    assert submit(engine, ocr, MARKER) == {"outcome": "inactive"}
    assert items(engine) == [] and media_files(engine) == []


def test_captured_frame_is_indexed_with_metadata(engine, ocr):
    enable(engine)
    assert engine.capture_screenshot_check({"app": "Editor", "app_known": True}) == {
        "allowed": True
    }
    result = submit(engine, ocr, MARKER)
    assert result["outcome"] == "captured"
    wait_indexed(engine, result["item_id"])
    item = engine.repo.get_item(result["item_id"])
    assert item.source_type == "screenshot"
    assert item.media_status == "present" and item.media_uri
    assert item.media_uri.startswith("screenshots/")
    assert item.metadata["display_id"] == "display-1"
    assert item.metadata["app"] == "Editor" and item.metadata["scale"] == 2.0
    assert item.source_label == "Editor"
    assert item.metadata["ocr_engine"] == "fake"
    stored = engine.media_root / item.media_uri
    assert stored.is_file() and stored.with_name(stored.stem + ".thumb.webp").is_file()
    hits = engine.search({"query": "observatory roadmap"})["results"]
    assert hits and hits[0]["item_id"] == item.id
    assert list((engine.media_root / "incoming").iterdir()) == []


def test_app_exclusion_refuses_before_capture_and_fails_closed(engine, ocr):
    enable(engine)
    engine.exclusions_add({"rule_type": "app", "rule_value": "Banking.exe"})
    check = engine.capture_screenshot_check({"app": "banking", "app_known": True})
    assert check == {"allowed": False, "reason": "excluded_app"}
    unknown = engine.capture_screenshot_check({"app": None, "app_known": False})
    assert unknown == {"allowed": False, "reason": "app_unknown"}
    # A frame sent anyway is refused again on intake.
    assert submit(engine, ocr, MARKER, app="Banking") == {"outcome": "excluded_app"}
    assert items(engine) == [] and media_files(engine) == []
    counts = engine.capture_get({})["session"]["screenshot"]
    assert counts == {"excluded_app": 2, "app_unknown": 1}


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("   ", "no_text"),
        ("deploy key ghp_" + "a" * 36, "sensitive"),
        ("salary review for the whole team", "excluded_pattern"),
    ],
)
def test_frames_dropped_after_ocr_leave_no_trace(engine, ocr, text, reason):
    enable(engine)
    engine.exclusions_add({"rule_type": "pattern", "rule_value": "salary review"})
    result = submit(engine, ocr, text)
    assert result["outcome"] == "captured"  # accepted for OCR
    wait_gone(engine, result["item_id"])
    assert items(engine) == []
    assert media_files(engine) == []
    assert engine.capture_get({})["session"]["screenshot"][reason] == 1
    jobs = engine.db.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert jobs == 0


def test_secret_filter_can_be_turned_off(engine, ocr):
    enable(engine)
    engine.settings_update({"changes": {"screenshot_detect_secrets": False}})
    result = submit(engine, ocr, "deploy key ghp_" + "b" * 36)
    wait_indexed(engine, result["item_id"])


def test_same_text_on_the_same_display_is_dropped(engine, ocr):
    enable(engine)
    first = submit(engine, ocr, MARKER)
    wait_indexed(engine, first["item_id"])
    second = submit(engine, ocr, MARKER)  # different pixels, same text
    wait_gone(engine, second["item_id"])
    assert [i["id"] for i in items(engine)] == [first["item_id"]]
    assert "last_seen_at" in engine.repo.get_item(first["item_id"]).metadata
    # The same text on another display is a separate frame.
    other = submit(engine, ocr, MARKER, display_id="display-2")
    wait_indexed(engine, other["item_id"])
    # Changed text on the first display is kept.
    changed = submit(engine, ocr, MARKER + " with new numbers")
    wait_indexed(engine, changed["item_id"])
    assert engine.capture_get({})["session"]["screenshot"]["same_text"] == 1


def test_identical_image_bytes_are_a_duplicate(engine, ocr):
    enable(engine)
    colour = (7, 7, 7)
    first = engine.capture_screenshot(frame(engine, ocr, MARKER, colour=colour))
    again = engine.capture_screenshot(frame(engine, ocr, MARKER, colour=colour))
    assert first["outcome"] == "captured"
    assert again == {"outcome": "duplicate_image"}
    assert len(items(engine)) == 1


def test_text_only_mode_keeps_text_and_drops_the_image(engine, ocr):
    enable(engine)
    engine.settings_update({"changes": {"text_only_mode": True}})
    result = submit(engine, ocr, MARKER)
    wait_indexed(engine, result["item_id"])
    item = engine.repo.get_item(result["item_id"])
    assert item.media_status == "pruned" and item.media_uri is None
    assert media_files(engine) == []
    assert engine.search({"query": "observatory roadmap"})["results"]


def test_ocr_unavailable_refuses_capture(engine, ocr):
    enable(engine)
    ocr.installed = False
    assert engine.capture_screenshot_check({"app_known": False}) == {
        "allowed": False,
        "reason": "ocr_unavailable",
    }
    assert engine.capture_get({})["ocr"]["available"] is False
    assert engine.formats_list({})["ocr_available"] is False


def test_frame_names_are_validated(engine, ocr):
    enable(engine)
    outside = engine.data_dir / "db" / "omnirecall.sqlite"
    for name in ("../db/omnirecall.sqlite", "shot-1.png", str(outside), "shot-" + "a" * 32):
        with pytest.raises((ValidationError, Exception)):
            engine.capture_screenshot(frame(engine, ocr, MARKER) | {"file": name})
    assert outside.is_file()
    missing = "shot-" + "c" * 32 + ".png"
    with pytest.raises(ValidationError):
        engine.capture_screenshot(frame(engine, ocr, MARKER) | {"file": missing})


def test_non_png_frame_is_refused_and_removed(engine, ocr):
    enable(engine)
    params = frame(engine, ocr, MARKER)
    path = engine.media_root / "incoming" / params["file"]
    path.write_bytes(b"not an image at all")
    with pytest.raises(ValidationError):
        engine.capture_screenshot(params)
    assert not path.exists() and items(engine) == []


def test_shell_skip_reasons_are_counted_and_validated(engine):
    engine.capture_screenshot_skip({"reason": "duplicate_image"})
    engine.capture_screenshot_skip({"reason": "idle"})
    with pytest.raises(Exception):  # noqa: B017 - schema rejects unknown reasons
        engine.capture_screenshot_skip({"reason": "made_up"})
    assert engine.capture_get({})["session"]["screenshot"] == {"duplicate_image": 1, "idle": 1}


def test_watcher_settings_are_published_with_capture_state(engine):
    state = engine.capture_get({})
    assert state["screenshot"] == {"interval_s": 30, "pause_on_idle_s": 300, "phash_threshold": 5}
    engine.notify.events.clear()
    engine.settings_update({"changes": {"screenshot_interval_s": 60}})
    sent = [p for m, p in engine.notify.events if m == "capture.state"]
    assert sent and sent[-1]["screenshot"]["interval_s"] == 60
    with pytest.raises(Exception):  # noqa: B017 - below the 5 s minimum
        engine.settings_update({"changes": {"screenshot_interval_s": 2}})
    # Pausing pushes the full state too, so the shell keeps the timing.
    engine.capture_pause({"paused": True})
    pushed = [p for m, p in engine.notify.events if m == "capture.state"][-1]
    assert pushed["paused"] is True and pushed["screenshot"]["interval_s"] == 60


def test_leftover_incoming_frames_are_removed_on_start(tmp_path, ocr):
    incoming = tmp_path / "data" / "media" / "incoming"
    incoming.mkdir(parents=True)
    leftover = incoming / f"shot-{uuid.uuid4().hex}.png"
    leftover.write_bytes(b"\x89PNG\r\n\x1a\n")
    eng = Engine(tmp_path / "data", None, Recorder(), embedder=HashEmbedder(), ocr=ocr)
    try:
        assert not leftover.exists()
    finally:
        eng.close()


def test_retention_prunes_screenshot_images_but_keeps_text(engine, ocr):
    enable(engine)
    result = submit(engine, ocr, MARKER)
    wait_indexed(engine, result["item_id"])
    engine.settings_update({"changes": {"screenshot_retention_days": 0}})
    item = engine.repo.get_item(result["item_id"])
    assert item.media_status == "pruned"
    assert media_files(engine) == []
    assert engine.search({"query": "observatory roadmap"})["results"]


def test_deleting_a_screenshot_removes_image_and_thumbnail(engine, ocr):
    enable(engine)
    result = submit(engine, ocr, MARKER)
    wait_indexed(engine, result["item_id"])
    assert len(media_files(engine)) == 2
    engine.delete_item({"item_id": result["item_id"]})
    wait_until(lambda: engine.repo.get_item(result["item_id"]).status == "deleted")
    assert media_files(engine) == []


def test_logs_never_contain_ocr_text(engine, ocr, monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(logs, "_stream", stream)
    monkeypatch.setattr(logs, "_min_level", 0)
    enable(engine)
    engine.exclusions_add({"rule_type": "pattern", "rule_value": "lighthouse"})
    kept = submit(engine, ocr, MARKER)
    dropped = submit(engine, ocr, "lighthouse " + MARKER)
    wait_indexed(engine, kept["item_id"])
    wait_gone(engine, dropped["item_id"])
    engine.search({"query": "pelican umbrella"})
    log = stream.getvalue()
    for needle in ("pelican", "umbrella", "observatory", "lighthouse", "Editor"):
        assert needle not in log, needle
    assert "screenshot_capture" in log
