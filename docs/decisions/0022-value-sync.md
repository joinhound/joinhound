# Value index sync

Approved fuzzy and semantic columns are copied into `kg.value_index`. Exact and normalized matches stay on the source. A column is indexed once; when several links name it, the first normalization expression wins. An unnamed expression is `fold` (trim, then lower). Embeddings are left null until a model is configured.

`scan_column` keeps its return type. After a scan, the PostgreSQL source sets `scan_cursor`. A table with `updated_at` yields rows newer than that timestamp. Other stable keys are split into 32 hash blocks, and only a block whose digest changed is read again. A heap addressed by `ctid` is one block and is replaced as a whole. The cursor is stored in `kg.value_sync`, which is not part of the published column schema: the block hashes have to survive between runs of `joinhound sync`.

`joinhound sync` prints `documents` and `values` counts.
