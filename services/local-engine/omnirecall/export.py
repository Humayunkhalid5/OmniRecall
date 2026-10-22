"""Export to one zip file (design.md §13, D-008).

Contents: ``manifest.json`` (app version, schema version, export time, item
count, SHA-256 of every other file), ``items.jsonl`` and ``chunks.jsonl`` with
the §5 fields, and ``media/`` with app-owned media that still exists. Vectors
are not exported; a restore rebuilds them.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

from omnirecall import __version__, logs
from omnirecall.errors import EngineError, ValidationError
from omnirecall.ids import utc_now
from omnirecall.storage.db import Database
from omnirecall.storage.media import TRANSIENT_DIR, owned_media_path

FORMAT_VERSION = 1
# Deleted rows hold only an ID and timestamps; they are not user data.
EXPORTED_STATUSES = ("queued", "processing", "indexed", "failed", "skipped")
ITEM_FIELDS = (
    "id",
    "source_type",
    "source_label",
    "source_uri",
    "captured_at",
    "content_hash",
    "media_uri",
    "media_status",
    "metadata_json",
    "status",
    "error_code",
    "skip_reason",
    "created_at",
    "updated_at",
)
CHUNK_FIELDS = (
    "id",
    "item_id",
    "ordinal",
    "text",
    "start_offset",
    "end_offset",
    "text_hash",
    "chunker_version",
    "embedding_model",
)


class _HashingWriter:
    """Writes to a zip member while hashing what was written."""

    def __init__(self, stream: IO[bytes]) -> None:
        self.stream = stream
        self.sha = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> None:
        self.sha.update(data)
        self.size += len(data)
        self.stream.write(data)


def validate_target(path_text: str, data_dir: Path) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        raise ValidationError("The export location must be a full path", "path")
    if path.suffix.lower() != ".zip":
        raise ValidationError("The export file must end in .zip", "path")
    parent = path.parent.resolve()
    if not parent.is_dir():
        raise ValidationError("The export folder does not exist", "path")
    target = parent / path.name
    if target.is_relative_to(data_dir.resolve()):
        raise ValidationError("Choose a location outside OmniRecall's data folder", "path")
    if target.is_dir():
        raise ValidationError("The export location is a folder", "path")
    return target


class Exporter:
    def __init__(self, db: Database, media_root: Path, data_dir: Path) -> None:
        self.db = db
        self.media_root = media_root
        self.data_dir = data_dir

    def export(
        self, path_text: str, progress: Callable[[int], None] | None = None
    ) -> dict[str, Any]:
        target = validate_target(path_text, self.data_dir)
        partial = target.with_name(target.name + ".partial")
        try:
            manifest = self._write(partial, progress)
            os.replace(partial, target)
        except OSError as exc:
            raise EngineError("export_failed", "The export file could not be written") from exc
        finally:
            with contextlib.suppress(OSError):
                partial.unlink(missing_ok=True)
        logs.info("export_created", count=manifest["item_count"], bytes=target.stat().st_size)
        return {
            "path": str(target),
            "item_count": manifest["item_count"],
            "chunk_count": manifest["chunk_count"],
            "media_count": manifest["media_count"],
            "bytes": target.stat().st_size,
        }

    def _write(self, partial: Path, progress: Callable[[int], None] | None) -> dict[str, Any]:
        files: dict[str, str] = {}
        placeholders = ",".join("?" * len(EXPORTED_STATUSES))
        # A separate connection gives one consistent snapshot for the whole export.
        conn = self.db.new_connection()
        try:
            conn.execute("BEGIN")
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                item_count = 0
                media: list[tuple[str, Path]] = []
                with zf.open("items.jsonl", "w") as raw:
                    out = _HashingWriter(raw)
                    rows = conn.execute(
                        f"SELECT {', '.join(ITEM_FIELDS)} FROM items "  # noqa: S608
                        f"WHERE status IN ({placeholders}) ORDER BY created_at, id",
                        EXPORTED_STATUSES,
                    )
                    for row in rows:
                        record = {k: row[k] for k in ITEM_FIELDS if k != "metadata_json"}
                        record["metadata"] = json.loads(row["metadata_json"])
                        out.write(json.dumps(record, ensure_ascii=False).encode() + b"\n")
                        item_count += 1
                        uri = row["media_uri"]
                        if (
                            row["media_status"] == "present"
                            and uri
                            and not uri.startswith(TRANSIENT_DIR + "/")
                        ):
                            source = owned_media_path(self.media_root, uri)
                            if source is not None and source.is_file():
                                media.append((uri, source))
                        if progress and item_count % 500 == 0:
                            progress(item_count)
                    files["items.jsonl"] = out.sha.hexdigest()

                chunk_count = 0
                with zf.open("chunks.jsonl", "w") as raw:
                    out = _HashingWriter(raw)
                    rows = conn.execute(
                        f"SELECT {', '.join('c.' + f for f in CHUNK_FIELDS)} FROM chunks c "  # noqa: S608
                        f"JOIN items i ON i.id = c.item_id WHERE i.status IN ({placeholders}) "
                        "ORDER BY c.item_id, c.ordinal",
                        EXPORTED_STATUSES,
                    )
                    for row in rows:
                        record = {k: row[k] for k in CHUNK_FIELDS}
                        out.write(json.dumps(record, ensure_ascii=False).encode() + b"\n")
                        chunk_count += 1
                    files["chunks.jsonl"] = out.sha.hexdigest()

                for uri, source in media:
                    name = f"media/{uri}"
                    sha = hashlib.sha256()
                    with source.open("rb") as src, zf.open(name, "w") as dst:
                        while block := src.read(1 << 20):
                            sha.update(block)
                            dst.write(block)
                    files[name] = sha.hexdigest()

                schema = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                manifest = {
                    "format": "omnirecall-export",
                    "format_version": FORMAT_VERSION,
                    "app_version": __version__,
                    "schema_version": schema,
                    "exported_at": utc_now(),
                    "item_count": item_count,
                    "chunk_count": chunk_count,
                    "media_count": len(media),
                    "vectors_included": False,
                    "files": {name: {"sha256": digest} for name, digest in sorted(files.items())},
                }
                zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        finally:
            conn.rollback()
            conn.close()
        return manifest
