"""SQLite access: connection setup, migrations, and transactions.

SQLite is the source of truth for metadata, chunk text, jobs, and settings
(rules.md §2.3). Every connection enables `secure_delete` so freed pages are
overwritten (design.md §7).
"""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from omnirecall import logs
from omnirecall.errors import EngineError
from omnirecall.ids import utc_now

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def _migrations() -> list[tuple[int, str]]:
    package = resources.files("omnirecall.storage") / "migrations"
    found: list[tuple[int, str]] = []
    for entry in package.iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.read_text(encoding="utf-8")))
    found.sort()
    versions = [v for v, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError("migration versions must be contiguous from 1")
    return found


LATEST_SCHEMA_VERSION = len(_migrations())


class Database:
    """Thread-local connections over one database file with a single writer lock.

    WAL mode lets readers (search) run while a writer (ingestion) commits.
    Writes are serialized in-process so they never fail with SQLITE_BUSY.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._all: list[sqlite3.Connection] = []
        self._all_lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._check_fts5()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA secure_delete = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        with self._all_lock:
            self._all.append(conn)
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def _check_fts5(self) -> None:
        probe = sqlite3.connect(":memory:")
        try:
            probe.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        except sqlite3.OperationalError as exc:
            raise EngineError(
                "fts5_unavailable", "This SQLite build lacks FTS5; keyword search cannot run"
            ) from exc
        finally:
            probe.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """A serialized IMMEDIATE transaction; rolls back on any exception."""
        with self._write_lock:
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def schema_version(self) -> int:
        conn = self.conn
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not exists:
            return 0
        row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        return int(row["v"] or 0)

    def migrate(self) -> list[int]:
        """Apply pending migrations in order, each in its own transaction."""
        applied: list[int] = []
        with self._write_lock:
            conn = self.conn
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            current = self.schema_version()
            if current > LATEST_SCHEMA_VERSION:
                raise EngineError(
                    "schema_too_new",
                    "This data was created by a newer OmniRecall version; update the app",
                    {"schema": current, "supported": LATEST_SCHEMA_VERSION},
                )
            for version, sql in _migrations():
                if version <= current:
                    continue
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _split_sql(sql):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                        (version, utc_now()),
                    )
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
                applied.append(version)
                logs.info("migration_applied", version=str(version))
        return applied

    def checkpoint(self) -> None:
        """Truncate the WAL so deleted rows do not linger in it (design.md §7)."""
        with self._write_lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def vacuum(self) -> None:
        """Rewrite the database file, dropping all free pages."""
        with self._write_lock:
            self.conn.execute("VACUUM")

    def close(self) -> None:
        with self._all_lock:
            for conn in self._all:
                try:
                    conn.close()
                except sqlite3.Error:
                    logs.warning("sqlite_close_failed")
            self._all.clear()
        self._local = threading.local()


def _split_sql(script: str) -> list[str]:
    """Split a migration into statements, keeping trigger bodies intact."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not buffer and (not stripped or stripped.startswith("--")):
            continue
        buffer.append(line)
        candidate = "\n".join(buffer)
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.strip())
            buffer = []
    if "\n".join(buffer).strip():
        raise RuntimeError("incomplete SQL statement in migration")
    return statements
