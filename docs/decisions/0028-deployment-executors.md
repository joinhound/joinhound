# Sidecar and co_located executors

`mode: sidecar` keeps the service schema in its own database. An exact or normalized step searches the source, then reads the chosen rows. `mode: co_located` is for a source whose owner allowed the `kg` schema in that same database. Exact and normalized steps then call `match_records`, one statement that returns the rows, and skip the second read. Fuzzy and semantic steps still use `kg.value_index`, because those matches are not a predicate the source can evaluate.

A source without `match_records`, or without the matching pushdown capability, stays on the two-step path even when the configuration says `co_located`.

## Alternatives

- Build indexes on the source columns and join `kg` with the customer tables in one statement. That needs write access to the customer database, which the project does not take.
- Pass a different matcher object per mode and leave `get_context` unaware of deployment. The walk still has to skip `fetch_by_keys` when the row was already read, so the choice belongs next to that read.
