# 0015. Stage 1 question gold and the SQL baseline

## Context

Stage 1 measures `get_context` on 20 Pagila questions and compares an agent that uses joinhound with an agent that uses a normal Postgres MCP server. The specification does not define the question file, which rows count as gold, or which Postgres MCP package is the baseline. Record URIs include a source name, and that name differs between configs.

## Decision

`tests/eval/gold/pagila_questions.json` holds 20 questions. Each gold URI is a row the answer must cite: the named record and the declared-foreign-key rows that identify it (for example the film, its `film_actor` rows, and the actors). Comparison ignores the source name and matches schema, table, and primary key.

`get_context` recall and precision are macro-averages over the 20 questions, using declared foreign keys from the catalog and the engine defaults. A recall drop of more than 0.02 from 0.7037 fails the integration test.

The baseline agent is not a third-party MCP package. It has two tools, `list_schema` and `query`, and `query` accepts one read-only `SELECT`. That is the schema-read plus SQL capability the specification names. The joinhound agent calls the stdio server's `get_context`, `expand`, and `get_record` tools. Both agents must cite `pg://` URIs. An answer is confirmed when at least one cited row was returned by a tool.

## Alternatives

- Treat every row in the walked neighborhood as gold. Recall would then measure the budget, not whether the answer's rows were found.
- Depend on an npm Postgres MCP server. The baseline would add a runtime and a license outside this repository for the same two capabilities.
- Pin precision in CI. Fanout cuts an unordered neighbor list, so the extra rows can change while the gold overlap stays put.
