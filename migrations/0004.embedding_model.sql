-- The model that produced kg.chunks.embedding and kg.value_index.embedding.
-- One row. A different model requires joinhound sync --reindex.

CREATE TABLE kg.embedding_model (
  model text NOT NULL,
  dim   int NOT NULL
);
