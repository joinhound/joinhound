# joinhound

> **Status: pre-alpha.** The first usable release is under development.

Joinhound connects to PostgreSQL and S3 with read-only credentials, proposes relationships between columns and document collections, and returns a bounded graph of related records and passages to an agent through MCP. Every item in the response carries the address of its source.

The project is open source under the Apache License 2.0. External contributions require a Developer Certificate of Origin sign-off, described in [CONTRIBUTING.md](CONTRIBUTING.md).

## Principles

- Customer sources are read-only. Joinhound stores metadata and indexes, not changes to the source.
- Relationships are rules between columns or between a column and a document collection. Pairs of individual records are found when a query runs.
- Every returned record or passage has a source URI.
- Only values needed for approved fuzzy or semantic relationships are copied, and sensitive columns can be stored as embeddings or hashes.
- Access rights from the source are applied to the result.
- Open standards are used wherever one exists. New sources, models, and relationship types plug in behind an interface.

Joinhound does not create geographic-proximity links or a permanent table of record pairs.

## Development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```console
uv sync
uv run joinhound --help
uv run jh --help
```

The published `0.0.1` package reserves the project name. Application commands are still being built.
