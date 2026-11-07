-- Every file Shelby keeps, in one store (layer 1b of plan.md). The file itself is at
-- <files root>/<id>/<name>, a folder named by an id that says nothing about whose it is; this row is its
-- record. Who owns a file is user_id, never a folder name.
--
-- kind says what it is for: audio to transcribe, a book (PDF) to read aloud, a voice sample to clone, or
-- docs (a folder of markdown to build into a Doc, under its own name). made_by says whether a person
-- uploaded it or the assistant wrote it (a draft): a draft is never the user's own material.
-- sha256 is of the file; for docs, of its files' names and hashes, in name order.

CREATE TABLE files (
    id         TEXT PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    user_id    UUID REFERENCES users (id) ON DELETE SET NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('audio', 'book', 'voice', 'docs')),
    name       TEXT NOT NULL,
    bytes      BIGINT NOT NULL,
    sha256     TEXT NOT NULL,
    made_by    TEXT NOT NULL CHECK (made_by IN ('user', 'assistant')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX files_kind_created ON files (kind, created_at DESC);
