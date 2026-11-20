-- What the model was asked to do and how many tokens it took: one row per request to a model (a chat step, or a
-- meeting's notes or minutes). The Overview adds these up and prices them. Tokens are kept, not dollars: a price is
-- worked out when the page asks (assistant/usage.py), so a corrected price fixes the past too. Nothing before this
-- file was recorded, so the Overview starts counting from the day it was applied.
--
-- source is `chat`, or the tool whose result carried the figures (`meet_ai__generate_notes`). input_tokens is what
-- the request sent that was not read from a cache, and output_tokens includes thinking. Neither assistant nor
-- meet-ai asks for caching, so there is no cache column; add one if that changes.

CREATE TABLE model_usage (
    id            BIGSERIAL PRIMARY KEY,
    used_at       TIMESTAMPTZ NOT NULL,
    source        TEXT NOT NULL,
    model         TEXT NOT NULL,
    provider      TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    user_id       UUID REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX model_usage_used_at ON model_usage (used_at);
