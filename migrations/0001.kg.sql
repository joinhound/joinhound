-- kg schema. vector(1024) is fixed for the selected embedding model.
-- Rows in kg.value_index describe values of one column. Record pairs are not stored.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA kg;

CREATE TABLE kg.sources (
  source_id   text PRIMARY KEY,
  kind        text NOT NULL,
  config      jsonb NOT NULL,
  created_at  timestamptz DEFAULT now()
);

CREATE TABLE kg.collections (
  collection_id text PRIMARY KEY,
  source_id     text REFERENCES kg.sources,
  kind          text NOT NULL,
  pk_columns    text[],
  row_estimate  bigint,
  synced_at     timestamptz
);

CREATE TABLE kg.columns (
  collection_id text REFERENCES kg.collections,
  column_name   text,
  type_class    text,
  n_distinct    double precision,
  null_ratio    real,
  uniqueness    real,
  pattern       text,
  minhash       bytea,
  profiled_at   timestamptz,
  PRIMARY KEY (collection_id, column_name)
);

CREATE TABLE kg.links (
  link_id        text PRIMARY KEY,
  src_collection text NOT NULL,
  src_column     text NOT NULL,
  dst_collection text NOT NULL,
  dst_column     text,
  match_type     text NOT NULL,
  origin         text NOT NULL,
  normalize_sql  text,
  threshold      real,
  confidence     real NOT NULL,
  relation_name  text,
  cardinality    text,
  rationale      text,
  status         text NOT NULL DEFAULT 'proposed',
  evidence       jsonb,
  updated_at     timestamptz DEFAULT now()
);

CREATE TABLE kg.value_index (
  collection_id text,
  column_name   text,
  pk            jsonb NOT NULL,
  norm_value    text,
  embedding     vector(1024),
  synced_at     timestamptz
);

CREATE INDEX kg_value_index_norm_value_trgm
  ON kg.value_index USING gin (norm_value gin_trgm_ops);
CREATE INDEX kg_value_index_embedding_hnsw
  ON kg.value_index USING hnsw (embedding vector_cosine_ops);
CREATE INDEX kg_value_index_lookup
  ON kg.value_index (collection_id, column_name, norm_value);

CREATE TABLE kg.documents (
  doc_id        text PRIMARY KEY,
  collection_id text REFERENCES kg.collections,
  etag          text,
  mime          text,
  acl           jsonb,
  parsed_at     timestamptz
);

CREATE TABLE kg.chunks (
  chunk_id   bigserial PRIMARY KEY,
  doc_id     text REFERENCES kg.documents ON DELETE CASCADE,
  page       int,
  bbox       real[4],
  text       text NOT NULL,
  tsv        tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
  embedding  vector(1024)
);

CREATE INDEX kg_chunks_tsv ON kg.chunks USING gin (tsv);
CREATE INDEX kg_chunks_text_trgm ON kg.chunks USING gin (text gin_trgm_ops);
CREATE INDEX kg_chunks_embedding_hnsw ON kg.chunks USING hnsw (embedding vector_cosine_ops);
