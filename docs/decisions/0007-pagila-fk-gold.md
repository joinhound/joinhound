# 0007. Pagila foreign-key gold file

## Context

`joinhound eval` compares `kg.links` with the foreign keys that were removed from a Pagila copy. The specification does not define the JSON file that holds those keys.

## Decision

`tests/eval/gold/pagila_fk.json` is an object with a `constraints` list. Each item has `schema`, `table`, `name`, `columns`, `ref_schema`, `ref_table`, and `ref_columns`. Column order is the foreign-key order. `joinhound eval` matches `schema.table` plus the column lists, and also accepts a `pg://source/schema.table` collection id.

## Alternatives

- Store one JSON object per column of a composite key. Pagila's declared keys are already one constraint each, and the constraint is the unit the script drops.
- Store `pg://` URIs in the gold file. The file would then depend on the source name chosen in a config.
