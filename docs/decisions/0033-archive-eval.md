# Archive evaluation set

The quality comparison needs a database and files, with questions whose answers are known. The historical-document archive from databasesample.com is CC0, version 4, and small enough to vendor. Its tables are authors, eras, materials, documents, and events. Its highlight paragraphs are the files.

The published documents table has no rare code, and its titles repeat. Each document therefore gets `archive_code` `ARC-` plus its id, and each highlight file starts with that code. The paragraph itself is not inserted into Postgres. A table-only search can still answer an author name. It cannot see a phrase that exists only in a file, and it cannot walk from that phrase to the document.

## Alternatives

- Pagila plus the generated invoice PDFs. Pagila is already the stage 1 set, and those PDFs do not name Pagila rows.
- A text-to-SQL benchmark such as Spider. Those questions have no files.
- Enron. The mail is public, and the corpus is too large to vendor.
