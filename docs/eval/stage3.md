# Stage 3 document eval

Two hundred generated PDFs and fifty questions in `tests/eval/gold/document_questions.json`. Eighty invoices, sixty specifications, and sixty letters. Forty PDFs have no text layer and stand in for scans. Each digital file names one code, a person, and an email. A question is that code. The gold URI is the object key; the page and the box are not part of the comparison.

`get_context` searched the passages produced by the PDF parser and the chunker. No embedding model was loaded, so only lexical seeds fired. Precision and recall are macro-averages.

- recall@budget: 0.800
- precision: 0.800
- latency p50: 0 ms
- latency p95: 0 ms

The forty digital questions score 1. The ten scan questions score 0, because a page with no text layer is not indexed unless OCR runs. The MVP targets are recall at least 0.8 and precision at least 0.6. This in-memory run finishes in under a millisecond per question, so it does not measure Postgres or S3 latency. The deployment target remains p95 under 2 seconds.

A column of all two hundred codes is proposed as a link to the collection. One hundred sixty codes occur in the text, so the confidence is 0.8.

The scan questions are `invoice-inv-1070`, `invoice-inv-1071`, `invoice-inv-1072`, `invoice-inv-1073`, `specification-spc-1130`, `specification-spc-1131`, `specification-spc-1132`, `letter-ltr-1190`, `letter-ltr-1191`, and `letter-ltr-1192`.

A SQL agent has no document reader, so it cannot return these object URIs. This measurement does not include a model call.
