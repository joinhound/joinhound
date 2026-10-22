# Query latency

`get_context` already sends every value of one column in a single `find_values` call, then reads the matched keys in one `fetch_by_keys` call. A step with several links still issues one batched lookup per link, because the links point at different tables.

Results of `get_context` are cached on the server for `engine.cache_ttl_seconds` (30 by default). The cache holds the response, not pairs of records, and an entry disappears when the TTL elapses. `expand` is not cached.

The engine stops a walk at `engine.timeout_ms`. Each source statement stops at `statement_timeout_ms`.

The measured gate is an indexed lookup of one code in a 10 million row table, and a query over 1 000 passages. Both must keep p95 under 2 seconds.

## Alternatives

- Cache record pairs. The project prohibition allows a result cache only with a TTL, and forbids a persistent pair table.
- Issue one SQL statement per value. That misses the p95 target once a step mentions more than a handful of values.
