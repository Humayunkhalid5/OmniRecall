-- 0001: initial schema (design.md §5). Applied once, inside a transaction.

CREATE TABLE items (
    id            TEXT PRIMARY KEY,
    source_type   TEXT NOT NULL,
    source_label  TEXT,
    source_uri    TEXT,
    captured_at   TEXT NOT NULL,
    content_hash  TEXT,
    media_uri     TEXT,
    media_status  TEXT NOT NULL DEFAULT 'none',   -- none | present | pruned | deleted
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL,
    error_code    TEXT,
    skip_reason   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CHECK (status IN ('queued','processing','indexed','failed','skipped','deleting','deleted')),
    CHECK (media_status IN ('none','present','pruned','deleted'))
);
CREATE UNIQUE INDEX items_source_hash ON items (source_type, content_hash);
CREATE INDEX items_status ON items (status);
CREATE INDEX items_captured_at ON items (captured_at);

CREATE TABLE chunks (
    id              TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    ordinal         INTEGER NOT NULL,
    text            TEXT NOT NULL,
    start_offset    INTEGER,
    end_offset      INTEGER,
    text_hash       TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (item_id, ordinal)
);
CREATE INDEX chunks_item ON chunks (item_id);
CREATE INDEX chunks_text_hash ON chunks (text_hash);

-- External-content FTS5 index over chunk text, kept in sync by triggers.
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='rowid',
    tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TRIGGER chunks_fts_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts (rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER chunks_fts_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER chunks_fts_update AFTER UPDATE OF text ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO chunks_fts (rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TABLE jobs (
    id              TEXT PRIMARY KEY,
    item_id         TEXT NOT NULL,
    stage           TEXT NOT NULL,
    status          TEXT NOT NULL,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error_code TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    CHECK (status IN ('pending','running','done','failed','cancelled'))
);
CREATE INDEX jobs_ready ON jobs (status, next_attempt_at);
CREATE INDEX jobs_item ON jobs (item_id);

CREATE TABLE vector_outbox (
    id            TEXT PRIMARY KEY,
    chunk_id      TEXT NOT NULL,
    operation     TEXT NOT NULL,
    vector_table  TEXT NOT NULL,
    status        TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CHECK (operation IN ('upsert','delete')),
    CHECK (status IN ('pending','done','failed'))
);
CREATE INDEX vector_outbox_pending ON vector_outbox (status, created_at);
CREATE INDEX vector_outbox_chunk ON vector_outbox (chunk_id);

CREATE TABLE tombstones (
    item_id        TEXT PRIMARY KEY,
    requested_at   TEXT NOT NULL,
    pending_stores TEXT NOT NULL,
    completed_at   TEXT
);

CREATE TABLE sources (
    id                 TEXT PRIMARY KEY,
    source_type        TEXT NOT NULL UNIQUE,
    enabled            INTEGER NOT NULL DEFAULT 0,
    configuration_json TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE exclusions (
    id         TEXT PRIMARY KEY,
    rule_type  TEXT NOT NULL,
    rule_value TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    CHECK (rule_type IN ('app','path','pattern'))
);

CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
