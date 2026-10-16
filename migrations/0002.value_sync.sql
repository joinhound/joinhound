-- Cursor for incremental scans of columns copied into kg.value_index.
-- The cursor stores block hashes, not pairs of records.

CREATE TABLE kg.value_sync (
  collection_id text NOT NULL,
  column_name   text NOT NULL,
  cursor        text NOT NULL,
  PRIMARY KEY (collection_id, column_name)
);
