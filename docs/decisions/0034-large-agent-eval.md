# Large agent evaluation

The archive smoke test proves only that a linked file can be traversed. It does
not compare joinhound with an alternative that can read the same files.

The effectiveness evaluation therefore uses the CC0 100K Library sample
database: 176,780 rows in 30 related tables. Preparation adds 10,000 circulation
case rows and 10,000 text case notes. A case note contains a unique natural
phrase and a case reference, but not the member, book, or branch that answers a
cross-source question.

The hard suite adds paraphrases, a rejected name inside the note, the staff
member who recorded the loan, and the book's publisher. The publisher is five
approved links away from the note. Flat retrieval stops after one hop, so it
can find the note without reaching that publisher. Both agent arms still see
the same files, schema, and read-only SQL.

The comparison has two baselines:

1. One-hop retrieval uses the same value dictionary and passage search, but
   stops before multi-hop traversal. This isolates the traversal effect without
   involving a model.
2. Both agent arms receive schema inspection, unrestricted read-only `SELECT`,
   and lexical search over every file. The joinhound arm additionally receives
   `get_context`, `expand`, and `get_record`. Arm order is randomized per
   question. The model, questions, tool-call limit, database, and files are
   identical.

Answer recall, confirmed-answer rate, tool calls, latency, and token use are
reported. Retrieval also reports evidence precision and recall. Results are
written to `cache/`; they are not golden assertions because model and hardware
measurements are observations, not unit tests.

## Alternatives

- Compare against database-only SQL. That withholds the files and is not a fair
  effectiveness baseline.
- Use the 1M library size. It costs more to run while the 100K size already has
  enough distractors for 10,000 files.
- Vendor the generated bundle. Ten thousand small files make source checkout
  slower; the pinned source and deterministic generator reproduce it.
