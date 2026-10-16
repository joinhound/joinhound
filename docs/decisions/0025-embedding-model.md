# Embedding model changes

The local embedder hashes character trigrams. `sentence-transformers` stays out of the dependency tree, as recorded for document indexing. The configured `embeddings.model` string is the model identity, whether the provider is `local`, `openai`, or `none`.

`kg.embedding_model` stores that name and the vector dimension after the first sync. A later run with a different name or dimension stops and tells the operator to run `joinhound sync --reindex`. That flag clears stored vectors, records the new model, and reads every source again.
