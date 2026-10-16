# 0011. What joinhound profile stores

## Context

`joinhound profile` has to write `kg.links` with evidence and honor `--auto-approve`. A later run must not insert a second row for the same pair or change a link that was already approved. The specification does not fix the `link_id` text or the evidence fields. `find_values(exact)` compares with `= ANY`, while the values it accepts and returns are strings, so an integer column would not match.

## Decision

`link_id` is `{collection}.{column}__{collection}.{column}`. A collection id drops its scheme and source, so `pg://shop/public.orders` contributes `public.orders`.

A declared single-column foreign key is stored as `declared_fk`, origin `catalog_fk`, status `approved`, confidence 1.0, cardinality `N:1`. An exact pair is stored as origin `discovered` and status `proposed`, with evidence `containment`, up to 10 matching sample values, and up to 5 misses. The same column pair is not stored again as exact.

`--auto-approve` overrides `profiler.auto_approve` for that run. A proposal whose confidence is at least the cutoff is inserted as `approved`. On conflict, only a row whose status is `proposed` is updated. Approved and rejected rows stay as they are.

Exact lookup compares `column::text` to the string values. Text columns still match, and integer keys match the strings the matcher already uses.

## Alternatives

- Use the full collection URI in `link_id`. The examples in the specification are table and column names.
- Delete proposals that disappear on the next run. A row under review would vanish.
- Compare integers with a typed array. The matcher protocol only carries strings.
