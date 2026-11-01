-- The text of every markdown upload and draft (layer 1b of plan.md). The database holds its only lasting copy:
-- a `docs` row in `files` is its record, and these rows are what it says, one per file, under the file's own
-- name (docu-ai gives each file a tab). A tool that reads one is handed a copy made for that call alone and
-- removed after it (texts.py); no tool reaches this table.

CREATE TABLE file_texts (
    file_id TEXT NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    name    TEXT NOT NULL,
    body    TEXT NOT NULL,
    PRIMARY KEY (file_id, name)
);
