-- Cached judge decisions. The key is a hash of the redacted prompt, not a record pair.

CREATE TABLE kg.judge_cache (
  cache_key  text PRIMARY KEY,
  verdict    jsonb NOT NULL,
  created_at timestamptz DEFAULT now()
);
