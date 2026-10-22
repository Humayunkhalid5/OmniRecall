"""End-to-end engine flows: import → index → search → detail → delete."""

from __future__ import annotations

import threading

import pytest
from docgen import write_pdf
from engine_support import make_engine, wait_status, wait_until
from pydantic import ValidationError as PydanticValidationError
from support import HashEmbedder

from omnirecall.errors import EngineError


@pytest.fixture
def engine(tmp_path):
    eng, _ = make_engine(tmp_path)
    yield eng
    eng.close()


def test_text_import_search_detail_delete(engine):
    out = engine.import_text(
        {"text": "The quarterly review moved to Thursday at 3pm", "label": "chat"}
    )
    item_id = out["item"]["id"]
    assert wait_status(engine, item_id, {"indexed", "failed"}) == "indexed"
    found = engine.search({"query": "quarterly review thursday"})
    assert found["results"][0]["item_id"] == item_id
    first = found["results"][0]
    assert first["matched_by"] in {"both", "keyword", "semantic"}
    assert first["captured_at"].endswith("Z") and first["snippet"]
    detail = engine.get_item({"item_id": item_id})
    assert detail["chunk_count"] == 1 and "Thursday" in detail["chunks"][0]["text"]
    # Payload file removed after indexing; chunks hold the text.
    assert detail["item"]["media_status"] == "none"
    assert not list((engine.media_root / "incoming").iterdir())

    assert engine.delete_item({"item_id": item_id})["status"] == "deleting"
    assert engine.search({"query": "quarterly review thursday"})["results"] == []
    wait_status(engine, item_id, {"deleted"})
    assert engine.index_verify({})["consistent"]


def test_duplicate_text_returns_existing(engine):
    a = engine.import_text({"text": "same text"})
    b = engine.import_text({"text": "same   text"})  # normalizes to the same content
    assert a["item"]["id"] == b["item"]["id"] and b["created"] is False


def test_file_import_and_formats(engine, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("Mitochondria produce ATP in the inner membrane")
    write_pdf(docs / "slides.pdf", ["Photosynthesis happens in the thylakoid"])
    (docs / "movie.mkv").write_bytes(b"x")
    (docs / ".hidden.txt").write_text("hidden")
    summary = engine.import_paths({"paths": [str(docs), str(tmp_path / "missing.txt")]})
    assert summary["queued"] == 2
    assert {"name": "missing.txt", "code": "not_found"} in summary["rejected"]
    for item_id in summary["item_ids"]:
        assert wait_status(engine, item_id, {"indexed", "failed"}) == "indexed"
    hit = engine.search({"query": "thylakoid"})["results"][0]
    assert hit["source_type"] == "file" and hit["source_label"] == "slides.pdf"
    detail = engine.get_item({"item_id": hit["item_id"]})
    assert detail["source_exists"] and detail["item"]["metadata"]["pages"] == 1
    again = engine.import_paths({"paths": [str(docs / "notes.md")]})
    assert again["duplicates"] == 1 and again["queued"] == 0


def test_missing_source_file_fails_visibly(engine, tmp_path):
    path = tmp_path / "gone.txt"
    path.write_text("will vanish before processing")
    engine.runner.stop()
    item_id = engine.import_paths({"paths": [str(path)]})["item_ids"][0]
    path.unlink()
    engine.runner.start()
    assert wait_status(engine, item_id, {"failed"}) == "failed"
    assert engine.repo.get_item(item_id).error_code == "source_missing"
    with pytest.raises(EngineError):
        engine.retry_item({"item_id": "01890000-0000-7000-8000-000000000000"})
    assert engine.retry_item({"item_id": item_id})["status"] == "queued"


def test_search_validation(engine):
    for bad in ["", "   "]:
        with pytest.raises(EngineError) as info:
            engine.search({"query": bad})
        assert info.value.code == "empty_query"
    with pytest.raises(EngineError) as info:
        engine.search({"query": "x" * 1001})
    assert info.value.code == "limit_exceeded"
    # FTS operators and quotes in user text are treated literally.
    assert engine.search({"query": 'NEAR("a" b) OR * AND -x "unclosed'})["results"] == []
    assert engine.search({"query": "!!! ???"})["count"] == 0


def test_search_filters_and_no_strong_match(engine):
    a = engine.import_text({"text": "Banana bread recipe with ripe bananas"})["item"]["id"]
    wait_status(engine, a, {"indexed"})
    result = engine.search({"query": "banana", "filters": {"source_types": ["clipboard"]}})
    assert result["results"] == []
    result = engine.search({"query": "banana", "filters": {"source_types": ["text"]}})
    assert result["results"][0]["item_id"] == a
    unrelated = engine.search({"query": "kubernetes pod logs"})
    assert unrelated["no_strong_match"] is True


def test_search_runs_while_ingesting(engine):
    for i in range(30):
        engine.import_text({"text": f"Document {i} about topic {i} with filler words " * 20})
    result = engine.search({"query": "topic 3"})
    assert "results" in result


def test_cancel_and_clear(engine):
    engine.runner.stop()
    item_id = engine.import_text({"text": "cancel me"})["item"]["id"]
    assert engine.cancel_job({"item_id": item_id})["status"] == "failed"
    engine.runner.start()
    other = engine.import_text({"text": "keep then clear"})["item"]["id"]
    wait_status(engine, other, {"indexed"})
    with pytest.raises(PydanticValidationError):
        engine.index_clear({})
    assert engine.index_clear({"confirm": True})["cleared"] == 2
    assert engine.status({})["items"] == {}
    # Engine keeps working after a clear.
    again = engine.import_text({"text": "after clear"})["item"]["id"]
    assert wait_status(engine, again, {"indexed"}) == "indexed"


def test_settings_validation(engine):
    updated = engine.settings_update({"changes": {"results_shown": 10}})
    assert updated["settings"]["results_shown"] == 10
    for bad in [{"results_shown": 0}, {"unknown_key": 1}, {"chunk_overlap": 600}]:
        with pytest.raises((PydanticValidationError, EngineError)):
            engine.settings_update({"changes": bad})
    assert engine.settings_get({})["settings"]["results_shown"] == 10


def test_restart_recovers_queue(tmp_path):
    eng, _ = make_engine(tmp_path)
    eng.runner.stop()
    item_id = eng.import_text({"text": "survives a restart"})["item"]["id"]
    eng.close()
    eng2, _ = make_engine(tmp_path)
    try:
        assert wait_status(eng2, item_id, {"indexed"}) == "indexed"
        wait_until(lambda: eng2.index_verify({})["consistent"])
    finally:
        eng2.close()


def test_status_shape(engine):
    status = engine.status({})
    assert status["encryption_at_rest"] is False
    assert status["model"]["installed"] is True
    assert {"db_bytes", "vector_bytes", "media_bytes", "data_dir"} <= status["storage"].keys()


class GatedEmbedder(HashEmbedder):
    """Embeds only once released, so items wait with their vectors pending."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()

    def embed(self, texts):
        self.gate.wait(20)
        return super().embed(texts)


def test_queue_capacity_counts_items_waiting_for_vectors(tmp_path):
    embedder = GatedEmbedder()
    eng, _ = make_engine(tmp_path, embedder=embedder)
    try:
        eng.settings_update({"changes": {"queue_capacity": 10}})
        ids = [
            eng.import_text({"text": f"harbor note number {i}", "label": "n"})["item"]["id"]
            for i in range(10)
        ]
        # Extraction finishes; only the vector writes are left.
        wait_until(lambda: eng.repo.active_job_count() == 0)
        assert eng.repo.backlog_count() == 10
        with pytest.raises(EngineError) as info:
            eng.import_text({"text": "one more harbor note", "label": "n"})
        assert info.value.code == "queue_full"
        embedder.gate.set()
        for item_id in ids:
            assert wait_status(eng, item_id, {"indexed", "failed"}) == "indexed"
        eng.import_text({"text": "one more harbor note", "label": "n"})
    finally:
        embedder.gate.set()
        eng.close()
