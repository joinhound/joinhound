# joinhound

> **Status: 0.1.0. Development stops at the measurements in this file.**

Joinhound connects to PostgreSQL and S3 with read-only credentials, proposes
relationships between columns and document collections, and returns a bounded
graph of related records and passages to an agent through MCP. Every item in
the response carries the address of its source.

The project is open source under the Apache License 2.0. External contributions
require a Developer Certificate of Origin sign-off, described in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Where it fits

Joinhound is a read-only context layer. It follows an approved link from a
document mention to a database row and returns that short chain. The link may
be fuzzy: a dossier can contain a misspelled or de-accented alias while the
table keeps the canonical value, and the tables need not declare a foreign key.

Two measured situations justify the tool.

A small model on a non-obvious link. On the 50-question fuzzy AmbER dev split,
`claude-haiku-4-5` with schema inspection, read-only SQL, and dossier search
scored 0.220 answer recall (0.040 confirmed). The same model with `get_context`
scored 0.980, confirmed 0.980, in 1.16 calls and 170,450 prompt tokens against
163,268. Forty-six answers used one call. The remaining miss shortened
`association football` to `football`.

An agent with no database credentials. The same questions, answered by
`claude-sonnet-5-5` from dossiers alone, scored 0.280 (0.120 confirmed in the
file text). Fourteen answers contained the gold string; six of those strings
were in the search output, and the other eight were inferences from the
distorted clue. Adding joinhound scored 1.000 and confirmed every answer.
Prompt tokens were 398,966 against 234,980, because that arm has no SQL path.

A strong model that can run SQL matches joinhound on answer quality and spends
fewer prompt tokens. `claude-sonnet-5-5` scored 1.000 from SQL and file search
on the library hard-dev set and on fuzzy AmbER. Joinhound scored 1.000 as well,
at 253,955 prompt tokens against 216,210 on fuzzy AmbER and 594,464 against
475,720 on the library hard-dev set. With the join hint removed and only the
public column list left, the SQL arm still scored 0.980. Column names were
enough to reconstruct those joins.

The untouched test splits of both suites were not run. Full protocols are in
[the library evaluation](docs/eval/library.md) and
[the AmbER evaluation](docs/eval/amber.md).

## Tests

Checks that ship with the repository:

```console
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src/joinhound/core src/joinhound/engine
uv run pytest
uv run lint-imports
uv run python scripts/check_licenses.py
```

`pytest` runs contract tests, unit tests, and integration tests. Integration
tests start PostgreSQL, MinIO, and related services through testcontainers.
The effectiveness comparisons below are separate scripts. They download CC0
data into `cache/`, which is not committed, and they do not run in `pytest`.
Agent arms need `LLM_API_KEY`, `LLM_BASE_URL`, and `JUDGE_MODEL`.

### Library

The library suite uses 176,780 CC0 rows, 10,000 generated case notes, and 500
questions. Both agent arms see the schema, read-only SQL, and every file. The
joinhound arm also receives `get_context`, `expand`, and `get_record`. Arm
order is randomized per question. The limit is eight tool calls.

Dev retrieval after the path budget, standard 250 questions: one hop 0.700
recall and 0.270 precision; five hops 0.990 and 0.109. Hard 125 questions: one
hop 0.500 and 0.275; five hops 0.956 and 0.150.

Hard-dev agent comparison, `claude-sonnet-5-5`, the same 125 questions:

| Arm | Answer recall | Confirmed | Calls | Latency | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQL and file search | 1.000 | 1.000 | 3.0 | 6871 ms | 475,720 |
| Same tools plus joinhound | 1.000 | 1.000 | 3.0 | 5351 ms | 594,464 |

### AmbER

AmbER uses 50 ambiguous names from CC0 AmbER Sets. Each name contributes one
head dossier and one tail dossier. The question asks for a property that is
not written in the dossier. The tables have no foreign keys. The fuzzy suite
strips diacritics from the clue and transposes two letters; the database keeps
the canonical alias.

Exact dev, `claude-sonnet-5-5`: both arms 1.000. SQL used 206,953 prompt
tokens. Joinhound used 476,307.

Fuzzy dev after the compact chain, same model: both arms 1.000. SQL used
216,210 prompt tokens and 3.4 calls. Joinhound used 253,955 and 2.4 calls.

Fuzzy dev, `claude-haiku-4-5`:

| Arm | Answer recall | Confirmed | Calls | Latency | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQL and dossier search | 0.220 | 0.040 | 1.90 | 3777 ms | 163,268 |
| Same tools plus joinhound | 0.980 | 0.980 | 1.16 | 2918 ms | 170,450 |

Fuzzy dev, dossiers only, `claude-sonnet-5-5`:

| Arm | Answer recall | Confirmed | Calls | Latency | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dossier search | 0.280 | 0.120 | 4.34 | 9207 ms | 234,980 |
| Dossier search plus joinhound | 1.000 | 1.000 | 3.08 | 8288 ms | 398,966 |

Fuzzy dev, SQL with the column list and no join hint, same model:

| Arm | Answer recall | Confirmed | Calls | Latency | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQL and dossier search | 0.980 | 0.940 | 3.24 | 6152 ms | 218,619 |
| Same tools plus joinhound | 1.000 | 1.000 | 2.60 | 5551 ms | 267,590 |

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

Local data services are defined in `docker-compose.yml`. The development
passwords in that file are only for this local stack.

```console
docker compose up --wait
scripts/load_pagila.sh
```

`kg-postgres` listens on port 55432, the Pagila source on port 55433, and
MinIO on port 59000. Follow [docs/quickstart.md](docs/quickstart.md) to connect
Pagila.

## MCP

`joinhound serve` speaks MCP over standard input and output. Point Claude
Desktop or Cursor at the command:

```json
{
  "mcpServers": {
    "joinhound": {
      "command": "joinhound",
      "args": ["serve", "--config", "/absolute/path/joinhound.yaml"]
    }
  }
}
```

Further reading: [configuration](docs/config.md),
[JOINHOUND Ossie extension](docs/ossie-extension.md), and
[plugins](docs/plugins.md).
