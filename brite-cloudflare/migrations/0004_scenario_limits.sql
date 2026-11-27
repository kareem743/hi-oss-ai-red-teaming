ALTER TABLE scenarios ADD COLUMN max_turns INTEGER NOT NULL DEFAULT 25 CHECK(typeof(max_turns)='integer' AND max_turns BETWEEN 1 AND 25);
ALTER TABLE scenarios ADD COLUMN max_context_chars INTEGER NOT NULL DEFAULT 80000 CHECK(typeof(max_context_chars)='integer' AND max_context_chars BETWEEN 1000 AND 80000);
