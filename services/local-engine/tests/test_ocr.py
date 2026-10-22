"""OCR adapter and image import (Phase 4), with the real Tesseract binary where present."""

from __future__ import annotations

import difflib
import shutil
from pathlib import Path

import pytest
from engine_support import make_engine, wait_status
from PIL import Image

from omnirecall.errors import EngineError, LimitExceededError
from omnirecall.extraction.ocr import (
    MAX_IMAGE_PIXELS,
    TesseractOcr,
    ocr_file,
    open_image,
    prepare,
)

FIXTURES = Path(__file__).parent / "fixtures" / "images"
needs_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="Tesseract is not installed"
)


def char_error_rate(reference: str, hypothesis: str) -> float:
    ref = " ".join(reference.split())
    hyp = " ".join(hypothesis.split())
    matcher = difflib.SequenceMatcher(None, ref, hyp)
    errors = sum(
        max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal"
    )
    return errors / max(len(ref), 1)


@needs_tesseract
@pytest.mark.parametrize("name", sorted(p.stem for p in FIXTURES.glob("*.png")))
def test_tesseract_reads_fixture_images(name):
    result = ocr_file(TesseractOcr(), FIXTURES / f"{name}.png")
    expected = (FIXTURES / f"{name}.txt").read_text()
    assert char_error_rate(expected, result.text) < 0.05
    assert result.metadata["ocr_engine"] == "tesseract"
    assert result.metadata["ocr_version"]


def test_missing_binary_is_reported_not_raised(tmp_path):
    ocr = TesseractOcr(command=str(tmp_path / "no-such-tesseract"))
    assert ocr.available() is False and ocr.version() is None
    with pytest.raises(EngineError) as info:
        ocr_file(ocr, FIXTURES / "chat_message.png")
    assert info.value.code == "ocr_unavailable"


def test_decompression_bomb_is_refused(tmp_path):
    bomb = tmp_path / "bomb.png"
    side = int(MAX_IMAGE_PIXELS**0.5) + 100
    Image.new("1", (side, side)).save(bomb)
    with pytest.raises(LimitExceededError):
        open_image(bomb)


def test_malformed_image_fails_cleanly(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    with pytest.raises(EngineError) as info:
        open_image(broken)
    assert info.value.code == "malformed_file"


def test_prepare_flattens_transparency_and_upscales_small_images():
    image = Image.new("RGBA", (400, 100), (0, 0, 0, 0))
    prepared = prepare(image)
    assert prepared.mode == "L"
    assert prepared.width == 1200  # capped at 3x
    assert prepared.getpixel((0, 0)) == 255  # transparent became white
    large = prepare(Image.new("RGB", (2000, 1000), "white"))
    assert large.size == (2000, 1000)


def test_multi_frame_images_use_the_first_frame(tmp_path):
    path = tmp_path / "anim.gif"
    first = Image.new("RGB", (20, 20), (255, 0, 0))
    second = Image.new("RGB", (20, 20), (0, 0, 255))
    first.save(path, save_all=True, append_images=[second])
    assert open_image(path).convert("RGB").getpixel((0, 0)) == (255, 0, 0)


@needs_tesseract
def test_image_import_is_searchable(tmp_path):
    engine, _ = make_engine(tmp_path)
    try:
        target = tmp_path / "shots"
        target.mkdir()
        shutil.copy(FIXTURES / "terminal_error.png", target / "terminal_error.png")
        (target / "notes.txt").write_text("unrelated notes about gardening")
        summary = engine.import_paths({"paths": [str(target)]})
        assert summary["queued"] == 2
        image_item = next(
            i for i in engine.list_items({})["items"] if i["source_label"] == "terminal_error.png"
        )
        assert wait_status(engine, image_item["id"], {"indexed", "failed"}, 60) == "indexed"
        item = engine.repo.get_item(image_item["id"])
        assert item.metadata["format"] == "image" and item.metadata["ocr_engine"] == "tesseract"
        expected = (FIXTURES / "terminal_error.txt").read_text().split("\n")[0]
        hits = engine.search({"query": expected})["results"]
        assert hits and hits[0]["item_id"] == item.id
    finally:
        engine.close()


def test_image_without_text_fails_with_a_clear_code(tmp_path):
    if shutil.which("tesseract") is None:
        pytest.skip("Tesseract is not installed")
    engine, _ = make_engine(tmp_path)
    try:
        blank = tmp_path / "blank.png"
        Image.new("RGB", (300, 200), "white").save(blank)
        item_id = engine.import_paths({"paths": [str(blank)]})["item_ids"][0]
        assert wait_status(engine, item_id, {"indexed", "failed"}, 60) == "failed"
        assert engine.repo.get_item(item_id).error_code == "extraction_empty"
    finally:
        engine.close()


def test_formats_list_includes_images(tmp_path):
    engine, _ = make_engine(tmp_path)
    try:
        formats = engine.formats_list({})
        extensions = {ext for f in formats["images"] for ext in f["extensions"]}
        assert {".png", ".jpg", ".webp", ".tiff"} <= extensions
        assert isinstance(formats["ocr_available"], bool)
    finally:
        engine.close()
