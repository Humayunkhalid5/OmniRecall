"""Build an upgrade fixture with a released version's own code.

Run from a checkout of that version, for example the Phase 4 release (schema 1):

    git worktree add ../or-phase4 6fce898
    cd ../or-phase4/services/local-engine
    PYTHONPATH=tests:. python \\
        <this repo>/services/local-engine/tests/fixtures/upgrade/make_fixture.py \\
        <this repo>/services/local-engine/tests/fixtures/upgrade/phase4-schema1.zip

The archive holds the data folder that version left behind (database, vector
table, stored screenshot) and a manifest of what is in it, so test_upgrade.py can
start the current engine on it and check nothing was lost.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from engine_support import Recorder, wait_status
from PIL import Image
from support import HashEmbedder

from omnirecall.app import Engine
from omnirecall.extraction.ocr import OcrResult

SHOT_TEXT = "Screenshot of the observatory booking form for the telescope night"


class FixedOcr:
    name = "fake"

    def available(self) -> bool:
        return True

    def version(self) -> str:
        return "1.0"

    def recognize(self, image: Image.Image) -> OcrResult:
        return OcrResult(SHOT_TEXT, {"ocr_engine": self.name})


def main(out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        docs = root / "docs"
        docs.mkdir()
        (docs / "garden.md").write_text(
            "# Garden plan\n\nPlant the tomatoes along the south fence in May.\n"
        )
        engine = Engine(root / "data", None, Recorder(), embedder=HashEmbedder(), ocr=FixedOcr())
        try:
            manifest: dict[str, object] = {"schema": engine.db.schema_version()}
            text = engine.import_text(
                {
                    "text": "Ferry timetable: the winter service leaves at 7:40 and 18:15.",
                    "label": "ferry",
                }
            )["item"]["id"]
            file_ids = engine.import_paths({"paths": [str(docs / "garden.md")]})["item_ids"]
            gone = engine.import_text({"text": "Old locker code note, removed later."})["item"][
                "id"
            ]
            for item_id in (text, *file_ids, gone):
                wait_status(engine, item_id, {"indexed"})

            engine.capture_set_source({"source_type": "clipboard", "enabled": True})
            clip = engine.capture_clipboard(
                {
                    "text": "Clipboard: library card renewal is due on the third of June",
                    "app": "Notes",
                    "app_known": True,
                }
            )
            engine.capture_set_source({"source_type": "screenshot", "enabled": True})
            buffer = io.BytesIO()
            Image.new("RGB", (64, 48), (12, 40, 80)).save(buffer, "PNG")
            name = f"shot-{uuid.uuid4().hex}.png"
            (engine.media_root / "incoming" / name).write_bytes(buffer.getvalue())
            shot = engine.capture_screenshot(
                {
                    "file": name,
                    "display_id": "display-1",
                    "app": "Browser",
                    "app_known": True,
                    "width": 64,
                    "height": 48,
                }
            )
            ids = {i["id"]: i for i in engine.list_items({"limit": 50})["items"]}
            clip_id = next(k for k, v in ids.items() if v["source_type"] == "clipboard")
            shot_id = next(k for k, v in ids.items() if v["source_type"] == "screenshot")
            for item_id in (clip_id, shot_id):
                wait_status(engine, item_id, {"indexed"})

            engine.delete_item({"item_id": gone})
            deadline = time.monotonic() + 20
            while engine.repo.get_item(gone).status != "deleted" and time.monotonic() < deadline:
                time.sleep(0.05)
            engine.exclusions_add({"rule_type": "app", "rule_value": "KeePassXC"})
            engine.exclusions_add({"rule_type": "pattern", "rule_value": "locker code"})
            engine.settings_update({"changes": {"first_run_completed": True, "results_shown": 30}})
            engine.capture_set_source({"source_type": "screenshot", "enabled": False})
            engine.db.checkpoint()
            manifest |= {
                "items": {
                    text: {"source_type": "text", "find": "ferry timetable"},
                    file_ids[0]: {"source_type": "file", "find": "tomatoes south fence"},
                    clip_id: {"source_type": "clipboard", "find": "library card renewal"},
                    shot_id: {"source_type": "screenshot", "find": "telescope night"},
                },
                "deleted": gone,
                "deleted_text": "locker code note",
                "media_uri": engine.repo.get_item(shot_id).media_uri,
                "clip_outcome": clip.get("outcome"),
                "shot_outcome": shot.get("outcome"),
            }
        finally:
            engine.close()

        data = root / "data"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
            for path in sorted(data.rglob("*")):
                rel = path.relative_to(data)
                if path.is_file() and rel.parts[0] not in ("logs", "models"):
                    archive.write(path, f"data/{rel.as_posix()}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
