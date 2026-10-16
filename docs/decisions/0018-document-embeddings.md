# Document embeddings

`kg.chunks.embedding` is `vector(1024)`. Indexing calls the configured
`Embedder` in batches of 64 and stores whatever vectors it returns. The
built-in provider `none` writes zero vectors of the configured dimension, so
`joinhound sync` can run without downloading a model.

The specification's default is a local `sentence-transformers` model. That
distribution pulls PyTorch and a model file, and this task does not add it.
The provider name and model in the configuration are the record of which
embedding was used. Changing `embeddings.model` means the collection has to
be indexed again; the schema has no separate model column.

The cursor passed back to an S3 source is the ETag map already stored on
`kg.documents`, in the JSON shape the connector accepts. A missing object in
that map is reported deleted and its row is removed. Chunks go with the
document because of `ON DELETE CASCADE`.
