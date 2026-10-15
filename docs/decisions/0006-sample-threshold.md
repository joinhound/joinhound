# 0006. Sample small PostgreSQL tables in primary-key order

## Context

The Postgres connector samples with `TABLESAMPLE SYSTEM` and reads a small table in full. The contract test needs the first sampled row of a known Pagila table to be stable. `TABLESAMPLE` is not stable, and a freshly loaded table often has no row estimate yet.

## Decision

When `pg_class.reltuples` is unknown or at most 10,000, `sample` reads rows in key order and applies `LIMIT`. Larger tables use `TABLESAMPLE SYSTEM`.

## Alternatives

- Always use `TABLESAMPLE`. The contract could not assert a specific Pagila row.
- Always read the whole table. That is the wrong plan for a large source.
