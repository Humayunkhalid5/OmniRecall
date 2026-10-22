"""Export zip (design §13) and media retention (design §11, §13)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import timedelta

import pytest
from engine_support import make_engine, wait_status

from omnirecall.errors import ValidationError
from omnirecall.ids import format_utc, parse_utc, utc_now
from omnirecall.storage.repository import NewItem


@pytest.fixture
def engine(tmp_path):
    eng, recorder = make_engine(tmp_path)
    eng.recorder = recorder
    yield eng
    eng.close()


def add_screenshot(engine, name: str, days_old: float, size: int) -> str:
    """A screenshot-like item with present media, as Phase 4 will create."""
    captured = format_utc(parse_utc(utc_now()) - timedelta(days=days_old))
    relative = f"screenshots/{name}.png"
    path = engine.media_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG" + bytes(size - 4))
    item, _ = engine.repo.create_item(
        NewItem(
            source_type="screenshot",
            captured_at=captured,
            content_hash=hashlib.sha256(name.encode()).hexdigest(),
            source_label=name,
            media_uri=relative,
        )
    )
    engine.repo.cancel_jobs(item.id)
    engine.repo.set_media_status(item.id, "present")
    return item.id


def test_export_zip_matches_documented_format(engine, tmp_path):
    a = engine.import_text({"text": "export me: the harbor plan", "label": "plan"})["item"]["id"]
    b = engine.import_text({"text": "second note, about otters"})["item"]["id"]
    wait_status(engine, a, {"indexed"})
    wait_status(engine, b, {"indexed"})
    shot = add_screenshot(engine, "s1", 1, 2048)
    gone = engine.import_text({"text": "deleted before export"})["item"]["id"]
    wait_status(engine, gone, {"indexed"})
    engine.delete_item({"item_id": gone})
    wait_status(engine, gone, {"deleted"})

    target = tmp_path / "out" / "omnirecall-export.zip"
    target.parent.mkdir()
    result = engine.export_create({"path": str(target)})
    assert result["item_count"] == 3 and result["media_count"] == 1
    assert not target.with_name(target.name + ".partial").exists()

    with zipfile.ZipFile(target) as zf:
        names = set(zf.namelist())
        assert names == {"manifest.json", "items.jsonl", "chunks.jsonl", "media/screenshots/s1.png"}
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["item_count"] == 3 and manifest["vectors_included"] is False
        assert manifest["schema_version"] >= 1 and manifest["exported_at"].endswith("Z")
        for name, entry in manifest["files"].items():
            assert hashlib.sha256(zf.read(name)).hexdigest() == entry["sha256"]
        items = [json.loads(line) for line in zf.read("items.jsonl").splitlines()]
        assert {i["id"] for i in items} == {a, b, shot}
        assert all("metadata" in i and "metadata_json" not in i for i in items)
        chunks = [json.loads(line) for line in zf.read("chunks.jsonl").splitlines()]
        assert {c["item_id"] for c in chunks} == {a, b}
        assert any("harbor plan" in c["text"] for c in chunks)
        assert "deleted before export" not in zf.read("chunks.jsonl").decode()


@pytest.mark.parametrize(
    "name", ["relative.zip", "noext", "{data}/inside.zip", "{tmp}/missing/x.zip"]
)
def test_export_rejects_bad_targets(engine, tmp_path, name):
    path = name.format(data=engine.data_dir / "exports", tmp=tmp_path)
    with pytest.raises(ValidationError):
        engine.export_create({"path": path})


def test_export_of_empty_index(engine, tmp_path):
    result = engine.export_create({"path": str(tmp_path / "empty.zip")})
    assert result["item_count"] == 0
    with zipfile.ZipFile(tmp_path / "empty.zip") as zf:
        assert zf.read("items.jsonl") == b""


def test_retention_prunes_old_screenshot_media_and_keeps_text(engine):
    old = add_screenshot(engine, "old", 8, 1000)
    fresh = add_screenshot(engine, "fresh", 1, 1000)
    report = engine.retention.run(engine._settings)
    assert report.pruned_by_age == 1 and report.pruned_by_cap == 0
    pruned = engine.repo.get_item(old)
    assert pruned.media_status == "pruned" and pruned.media_uri is None
    assert not (engine.media_root / "screenshots" / "old.png").exists()
    assert engine.repo.get_item(fresh).media_status == "present"


def test_media_cap_prunes_oldest_first(engine):
    first = add_screenshot(engine, "a", 3, 4000)
    second = add_screenshot(engine, "b", 2, 4000)
    third = add_screenshot(engine, "c", 1, 4000)
    engine.settings_update({"changes": {"media_cap_bytes": 9000}})
    assert engine.repo.get_item(first).media_status == "pruned"
    assert engine.repo.get_item(second).media_status == "present"
    assert engine.repo.get_item(third).media_status == "present"
    assert engine.storage_usage({})["media_bytes"] == 8000
    assert ("media.pruned", {"pruned_by_age": 0, "pruned_by_cap": 1, "media_bytes": 8000}) in (
        engine.recorder.events
    )


def test_zero_retention_keeps_no_images(engine):
    item = add_screenshot(engine, "now", 0, 500)
    engine.settings_update({"changes": {"screenshot_retention_days": 0}})
    assert engine.repo.get_item(item).media_status == "pruned"


def test_retention_never_touches_text_items(engine):
    out = engine.import_text({"text": "keep this text forever"})["item"]["id"]
    wait_status(engine, out, {"indexed"})
    engine.settings_update({"changes": {"media_cap_bytes": 0}})
    assert engine.search({"query": "keep this text"})["results"][0]["item_id"] == out
