"""Recover what can be read from a damaged database file (D-036).

SQLite holds the only copy of chunk text, settings, and exclusions, so a
damaged file is not rebuilt from anything: rows are copied one range at a time
into a new database with the current schema, and ranges that cannot be read
are skipped and counted. The keyword index, vectors, and jobs are derived and
are rebuilt by the normal startup reconciliation afterwards.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from omnirecall import logs
from omnirecall.storage.db import Database

# Copied in dependency order (chunks reference items). Everything else is derived.
COPY_TABLES = ("settings", "sources", "exclusions", "items", "tombstones", "chunks")
BATCH = 500
# How far to jump past an unreadable rowid before trying again (doubles each time).
FIRST_SKIP = 1
MAX_SKIPS = 64


class DatabaseDamagedError(Exception):
    """The database file cannot be opened or failed its integrity check."""


SQLITE_CORRUPT = 11
SQLITE_NOTADB = 26


def damage_reason(exc: sqlite3.Error) -> str | None:
    """The reason code if `exc` reports a damaged file; None for anything else."""
    code = getattr(exc, "sqlite_errorcode", None)
    primary = code & 0xFF if isinstance(code, int) else None
    if primary == SQLITE_NOTADB:
        return "not_a_database"
    if primary == SQLITE_CORRUPT:
        return "malformed"
    return None


def check(path: Path) -> str | None:
    """None if the file opens and passes `PRAGMA quick_check`, else the reason code.

    Only damage counts: a locked file, a full disk, or a permission error is not
    damage, so it is left for the normal start to report instead of offering
    to replace the database.
    """
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute("PRAGMA quick_check(1)").fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return damage_reason(exc)
    return None if rows == [("ok",)] else "malformed"


@dataclass
class SalvageReport:
    copied: dict[str, int] = field(default_factory=dict)
    unreadable_ranges: dict[str, int] = field(default_factory=dict)
    dropped_orphans: int = 0
    # Items whose text was on unreadable pages: files are extracted again,
    # other items (pasted text, clipboard, screenshots) are marked as lost.
    requeued: int = 0
    lost: int = 0

    @property
    def complete(self) -> bool:
        return not any(self.unreadable_ranges.values())

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"complete": self.complete}


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _copy_table(
    old: sqlite3.Connection, new: sqlite3.Connection, table: str, report: SalvageReport
) -> None:
    try:
        old_cols = set(_columns(old, table))
    except sqlite3.DatabaseError:
        report.unreadable_ranges[table] = 1
        return
    cols = [c for c in _columns(new, table) if c in old_cols]
    if not cols:
        return
    names = ",".join(cols)
    marks = ",".join("?" * len(cols))
    insert = f"INSERT OR IGNORE INTO {table} ({names}) VALUES ({marks})"  # noqa: S608
    select = f"SELECT rowid, {names} FROM {table} WHERE rowid > ? ORDER BY rowid LIMIT ?"  # noqa: S608
    last, copied, skipped, skip = -(2**63), 0, 0, FIRST_SKIP
    while True:
        try:
            rows = old.execute(select, (last, BATCH)).fetchall()
        except sqlite3.DatabaseError:
            # Read row by row up to the bad page, then jump past it.
            try:
                rows = old.execute(select, (last, 1)).fetchall()
            except sqlite3.DatabaseError:
                skipped += 1
                if skipped > MAX_SKIPS:
                    break
                last += skip
                skip *= 2
                continue
        if not rows:
            break
        skip = FIRST_SKIP
        new.executemany(insert, [tuple(r[1:]) for r in rows])
        copied += len(rows)
        last = rows[-1][0]
    report.copied[table] = copied
    report.unreadable_ranges[table] = skipped


def _mark_items_without_text(conn: sqlite3.Connection, report: SalvageReport) -> None:
    """An indexed item must have all its chunks; otherwise redo it or report it lost."""
    short = conn.execute(
        "SELECT i.id, i.source_type FROM items i WHERE i.status = 'indexed' AND "
        "(SELECT COUNT(*) FROM chunks c WHERE c.item_id = i.id) "
        "< COALESCE(json_extract(i.metadata_json, '$.chunks'), 1)"
    ).fetchall()
    for item_id, source_type in short:
        if source_type == "file":
            # The original file is read again; startup reconciliation queues it.
            conn.execute("DELETE FROM chunks WHERE item_id = ?", (item_id,))
            conn.execute(
                "UPDATE items SET status = 'queued', error_code = NULL WHERE id = ?", (item_id,)
            )
            report.requeued += 1
        else:
            conn.execute("DELETE FROM chunks WHERE item_id = ?", (item_id,))
            conn.execute(
                "UPDATE items SET status = 'failed', error_code = 'recovery_lost_text' "
                "WHERE id = ?",
                (item_id,),
            )
            report.lost += 1


def salvage(damaged: Path, target: Path) -> SalvageReport:
    """Copy every readable row of `damaged` into a new database at `target`."""
    target.unlink(missing_ok=True)
    fresh = Database(target)
    fresh.migrate()
    fresh.close()
    report = SalvageReport()
    old = sqlite3.connect(f"file:{damaged}?mode=ro", uri=True)
    new = sqlite3.connect(target, isolation_level=None)
    try:
        new.execute("PRAGMA foreign_keys = OFF")
        new.execute("BEGIN")
        # The fresh schema seeds default settings and sources; recovered rows win.
        for table in ("settings", "sources"):
            new.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed names
        for table in COPY_TABLES:
            _copy_table(old, new, table, report)
        if not any(report.copied.values()):
            raise DatabaseDamagedError("no row could be read")
        cur = new.execute("DELETE FROM chunks WHERE item_id NOT IN (SELECT id FROM items)")
        report.dropped_orphans = cur.rowcount
        _mark_items_without_text(new, report)
        new.execute("INSERT INTO chunks_fts (chunks_fts) VALUES ('rebuild')")
        new.execute("COMMIT")
        new.execute("PRAGMA foreign_keys = ON")
        bad = new.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise DatabaseDamagedError("recovered rows break foreign keys")
    finally:
        old.close()
        new.close()
    logs.info(
        "database_salvaged",
        count=sum(report.copied.values()),
        status="complete" if report.complete else "partial",
    )
    return report
