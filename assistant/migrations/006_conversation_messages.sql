-- What the model remembers of a conversation: the API's own messages (the words, the tools it called and what they
-- returned, its thinking), kept so a past conversation can be continued where it left off. Null for a conversation
-- kept before this column: continuing one rebuilds it from the words Chat showed.

ALTER TABLE conversations ADD COLUMN messages JSONB;
