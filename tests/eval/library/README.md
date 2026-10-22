# Library agent evaluation

The large comparison uses version 2 of the
[Library sample database](https://databasesample.com/datasets/library-sample-database),
licensed CC0 1.0. The 100K PostgreSQL artifact has 176,780 rows in 30 tables.
It is downloaded into `cache/`, not committed.

`scripts/prepare_library_eval.py` verifies the artifact SHA-256, loads an empty
PostgreSQL database, creates 10,000 circulation cases, and writes one unstructured
case note for each case. It also writes 500 balanced questions:

- 100 direct database questions;
- 100 direct file questions;
- 100 file-to-member questions;
- 100 file-to-book questions;
- 100 file-to-library questions.

The note contains a case reference but none of the expected member, book, or
library answers. Cross-source questions therefore require a file search followed
by database traversal.

The run has two comparisons:

1. Flat, one-hop retrieval versus joinhound traversal, with no model.
2. One model with `describe_schema` + read-only SQL + full file search in both
   arms; the joinhound arm additionally receives `get_context`. Both arms receive
   the same questions, data, maximum tool calls, and model. Their execution order
   is randomized per question.

The generated bundle and result JSON remain under `cache/library-eval/`.
