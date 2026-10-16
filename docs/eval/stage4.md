# Stage 4 latency

Measured by `tests/integration/test_scale.py` and `tests/unit/test_latency.py`.

| Workload | Gate | Result |
| --- | --- | --- |
| Indexed lookup of one code in 10,000,000 rows | p95 < 2 s | passed |
| Query over 1,000 passages | p95 < 2 s | passed |

The 10 million row run, including table creation, finished in about 11 seconds on the development machine. The test fails if the query p95 reaches 2 seconds. The passage query is in memory and does not call a model.

One step sends every value of a column in a single source query. `get_context` responses are reused for `engine.cache_ttl_seconds` (30 by default) and are not stored as record pairs.
