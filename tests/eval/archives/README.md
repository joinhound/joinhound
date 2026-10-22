# Historical document archive

Catalog rows are the CC0 dataset [Historical documents with eras, authors, materials and events](https://databasesample.com/datasets/historical-document-archives), version 4. The JSON file is `historical-document-archives.json`. Its SHA-256 is `00aaa114b7cb11186be477602c8641227abeb21997c51d7b1f36be41d1a77cb7`.

`files/` holds one text file per `document_highlights` row. The highlight paragraph is not loaded into the database. Each file starts with `ARC-` and the document id, and that same code is stored on `documents.archive_code`. The published table has no such code; the evaluation adds it so a column can point at the file that quotes the document.

The comparison is in `docs/eval/archives.md`.
