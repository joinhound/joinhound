# 0013. How the first context query finds and scores rows

## Context

T1.6 asks for dictionary seeds, exact value search, beam search, scoring, a token budget, and a Pydantic response. The specification also describes lexical search, semantic search, and an automaton built during sync. Those indexes and the sync command are later tasks. Pagila's approved links name surrogate keys, so a query cannot mention a film title if the dictionary contains only those keys. The specification's relevance term is a cosine, and the embedding index does not exist yet.

## Decision

Seeds come from one channel. An Aho-Corasick automaton matches column values in the query, and `find_values(exact)` loads the rows. The automaton indexes columns named by approved links and text columns of those collections. A value is kept when its length is 3 to 80 characters, and a hit must start and end on a token boundary. Matching is case-sensitive, the same rule as exact lookup.

`get_context` builds the automaton when the caller does not pass one. Only approved links are walked. `declared_fk` and `exact` run on the source: the matcher resolves a foreign-key value to the parent row, and `find_values(exact)` finds child rows. Other match types are left for later tasks. Neighbors are ordered by primary key and then cut to `fanout` per node and link. The initial seeds are cut to `seeds_k`, and each later step keeps `beam_width` nodes.

The path score is the specification's product: word-count cosine scaled from [0, 1] into [0.3, 1], times each edge score, times `depth_decay` to the depth. An exact edge scores `1` times the link confidence. Tokens are `tiktoken` cl100k over the JSON of non-null columns. Nodes are added in score order until the next one would pass `budget_tokens`. A timeout returns what was collected and sets `truncated`.

`pyahocorasick` 2.2.0 declares BSD-3-Clause AND Public Domain. `tiktoken` 0.12.0 is MIT, but its metadata pastes the license text instead of the classifier, and it depends on `regex`, which declares Apache-2.0 AND CNRI-Python. Public Domain and CNRI-Python are permissive, so the license check accepts them.

## Alternatives

- Index only the columns named by links. A Pagila title would never be a seed.
- Call an embedding model for the cosine. The score would depend on a provider and would not be stable offline.
- Wait for sync to build the automaton. The traversal tests could not run in this task.
