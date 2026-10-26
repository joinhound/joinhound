# 0037. Return one asked chain and match a close dossier mention

## Context

On the exact AmbER dev split both agent arms answered every question.
Joinhound used about 2.3 times as many prompt tokens because `get_context`
returned every seed and several sibling facts. The dossier clue was also an
exact alias, so read-only SQL could join it without a fuzzy comparison.

## Decision

When the best seed has a descendant whose field value is a phrase in the
question outside any quoted span, the response keeps only that chain. The
chosen descendant is the one whose path passes through a name or title that
occurs in the seed text, then the longest path value that occurs there,
exactly or at rapidfuzz partial ratio 0.85 after diacritics are stripped. A seed found again from a higher-scoring seed is
attached to that path so the asked row stays on the chain. Other seeds and
sibling rows stay out of the response.

Document mentions stay exact when a column value of at least twelve
characters occurs in the fragment. A shorter exact token such as `army` or
`of` loses to one longer value whose diacritic-folded form has partial ratio
at least 0.85. If nothing matches exactly, that same approximate mention is
used. The passage named by a distinctive phrase in the question stays in the
seed set, and a fact reached from that passage stays on its chain. The compact
response keeps the passage lines the question names, the subject, and the
asked fact.

The fuzzy AmbER suite writes that distorted clue into the dossier and leaves
the canonical alias in the database. Preparation uses `--distort` and writes
`cache/amber-eval/bundle-fuzzy`. The dev split is the measurement set. The
test split stays untouched. An arm that exhausts its tool-call budget without
submitting an answer scores zero on that question. A failed read-only query is
returned to the model as a tool error.

On the fuzzy dev split, `claude-sonnet-5-5` still scores 1.000 in both arms.
After the chain returns the asked value, `claude-haiku-4-5` scores 0.220 with
SQL and dossier search, and 0.980 with joinhound, at 170,450 prompt tokens
against 163,268. With SQL removed, the same Sonnet model scores 0.280 from
dossier search and 1.000 with joinhound. With SQL kept and the join hint
removed, Sonnet scores 0.980 from the column list. The numbers are in
`docs/eval/amber.md`.

## Alternatives

Lowering the SQL arm's tool-call limit made the baseline time out, so the
comparison keeps eight calls. Returning every seed preserves recall on broad
questions but keeps the token cost that the compact chain is meant to remove.
A quoted span is ignored so a library question that quotes a note does not
collapse onto a word inside that note.
