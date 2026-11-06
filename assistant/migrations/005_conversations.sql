-- Chat conversation history: each cleared or switched-away conversation is kept for the sidebar to list
-- and load. Events are the full stream the frontend rendered, stored as JSONB so loading a past
-- conversation is one read that Chat.tsx can show unchanged.

CREATE TABLE conversations (
    id         TEXT PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    title      TEXT NOT NULL DEFAULT '',
    events     JSONB NOT NULL DEFAULT '[]'::jsonb,
    message_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX conversations_updated ON conversations (updated_at DESC);
