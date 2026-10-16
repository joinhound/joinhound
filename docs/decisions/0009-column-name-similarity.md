# 0009. Column-name similarity and year predominance

## Context

The integer-id rule keeps a pair when the source column name resembles the destination, with `customer_id` and `customers.id` as the example. It does not define the comparison. A year column is an integer column whose values are predominantly between 1900 and 2100. "Predominantly" has no numeric cutoff.

## Decision

Names are split on non-letters. Generic tokens `id`, `key`, `pk`, `code`, `num`, `no`, and `number` are ignored. A trailing plural `s` is removed. The source column's remaining tokens must each be within one edit of a token from the destination column or its table name. When the column name has no distinctive token, the source table name is used instead.

A column is a year column when more than half of its sampled values are integers from 1900 through 2100. Both cutoffs are `ProfilerConfig` fields.

## Alternatives

- Compare the raw strings `customer_id` and `id`. That misses the example, because the shared word is on the table.
- Require every value to be a year. A column with a few sentinels would stay in the pair search.
