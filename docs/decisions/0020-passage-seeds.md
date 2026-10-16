# Passage seeds

Lexical and semantic ranks are fused with reciprocal rank fusion, k = 60.
The lexical rank keeps a fragment when every word of the query occurs in it.
That is the in-memory form of a simple AND text query over the chunk text
`joinhound sync` already stores. Semantic rank is cosine similarity against
the stored embedding, and only runs when the caller supplies an embedder.

A fragment with no roles is readable. A fragment with roles is readable only
when the caller shares one of them. The check happens before a node is
scored, so an inaccessible collection contributes no node, edge, path, or
expandable id.
