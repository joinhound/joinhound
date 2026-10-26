# 0035. Return the best paths instead of the whole neighborhood

## Context

`get_context` walked every approved link to `max_depth` and then filled `budget_tokens` with the highest-scoring nodes. On a wide schema the token budget held hundreds of identifier-only neighbors. Recall of a distant answer stayed high, but precision fell to about 1% and the serialized graph dominated the model prompt.

The response schema from decision 0013 stays the same: nodes, edges, paths, `truncated`, and `expandable`.

## Decision

The walk still explores approved links. Two limits change what is discovered and returned:

- Reverse links from a seed still use `fanout`. Reverse links from a later node use `child_fanout`, which defaults to 2. Forward children of the two highest-scoring seeds stay on the beam when an intermediate row does not repeat the query.
- Passage search keeps the note that places the most distinctive query words in one sentence, so a question can name the target without repeating every word in the note.
- A node's traversal score carries the strongest relevance seen from its seed, while final reranking also considers the node's own relevance. Returned paths come from the strongest seed: one direct forward row per collection, the best row of each collection named in the question, then the highest-ranking rows on that chain. A reverse row ranks behind a forward row unless one of its values is a phrase in the question. A row with words the query did not already contain, or whose collection name shares a stem with the query, ranks ahead of an identifier-only row.
- The response keeps every seed that fits the budget, then at most `max_paths` paths. The default is 16.

A node in the context graph keeps strings and values mentioned by the query. Surrogate keys and boxes stay out of that payload. `get_record` still returns the full row, and `expand` walks from a returned URI when `truncated` is true.

A path that started from a document may resolve database rows, but those rows
do not lead back into other documents through the same document link. This
prevents a shared value from spreading one dossier query across the corpus.

The library evaluation uses a tighter budget than the product default: four seeds, six paths, child fanout 1, and 2,000 tokens.

## Alternatives

- Lower only the library evaluation's token budget. The same wide walk would remain the product behavior.
- Drop reverse traversal. Questions such as "who acts in this film?" reach the actors through the reverse direction of a foreign key.
- Add a new response field for paths. The existing `paths` array already gives that order.
