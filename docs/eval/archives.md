# Archive traversal smoke test

This small check is not an effectiveness comparison. Its table-only arm cannot
read the highlight files, so a file phrase must score zero there. The fair
comparison, where the baseline can read the same database and files, is
`docs/eval/library.md`.

The dataset is the CC0 historical-document archive in `tests/eval/archives/`. Five catalog tables are the database. One hundred fifty highlight paragraphs are files. A question set has eight author names, eight phrases that occur in one file, and the same eight phrases scored against both that file and its document row.

`get_context` runs twice. Without the files it sees only the tables and their declared foreign keys. With the files it also sees the passages and one approved link from `documents.archive_code` to the file collection. The token budget is wide, so the score is about what can be reached.

| Questions | Without the files | With the files |
| --- | ---: | ---: |
| Author names | 1.000 | 1.000 |
| Highlight phrases, file only | 0.000 | 1.000 |
| Highlight phrases, file and document row | 0.000 | 1.000 |

Recall is the share of gold URIs returned. Author questions stay at 1 because those names are column values. Phrase questions stay at 0 until the files are visible. The link then carries the passage back to the document row whose code is written in the file.

Precision stays low on every group. A foreign key still pulls in neighboring rows, as it did on Pagila.
