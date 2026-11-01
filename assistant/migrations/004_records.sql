-- What tools made that the suite keeps (layer 1b of plan.md, phase B; shape A, the user's choice of 2026-11-01).
-- A tool labels each thing it made -- kind, key, labels, text, files -- and the assistant files it here under
-- those labels without knowing what it is (records.py). One record per (tool, kind, key): filing the same key
-- again replaces it. labels are the tool's own words, kept as it gave them; body is the record's text, if any (a
-- chapter's exact spoken words); version is the tool's, so the same thing is not filed twice.

CREATE TABLE records (
    id         TEXT PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    user_id    UUID REFERENCES users (id) ON DELETE SET NULL,
    tool       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    labels     JSONB NOT NULL DEFAULT '{}',
    body       TEXT,
    version    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tool, kind, key)
);
CREATE INDEX records_tool_kind ON records (tool, kind, updated_at DESC);

-- Which stored file plays which part in a record (a chapter's audio; a voice's sample and state). A file in the
-- store is not deleted while a record still names it.
CREATE TABLE record_files (
    record_id TEXT NOT NULL REFERENCES records (id) ON DELETE CASCADE,
    role      TEXT NOT NULL,
    file_id   TEXT NOT NULL REFERENCES files (id) ON DELETE RESTRICT,
    PRIMARY KEY (record_id, role)
);

-- A file a tool made: kept in the store, never listed among uploads. made_by says so.
ALTER TABLE files DROP CONSTRAINT files_kind_check,
    ADD CONSTRAINT files_kind_check CHECK (kind IN ('audio', 'book', 'voice', 'docs', 'made'));
ALTER TABLE files DROP CONSTRAINT files_made_by_check,
    ADD CONSTRAINT files_made_by_check CHECK (made_by IN ('user', 'assistant', 'tool'));
