# Fuzzy similarity

Discovery scores a sampled pair with `rapidfuzz.fuzz.ratio` after `fold` (trim, then lower). A value counts when its best destination score is at least 0.6, and the pair is proposed when that fraction meets the containment threshold. A pair that already matches under `fold` is left to the normalized matcher.

Execution against `kg.value_index` uses `pg_trgm` `similarity` with the same 0.6 cutoff. The two functions are not identical. The threshold is the one in the profiler section, applied to each implementation. Without an index DSN, resolution scans the source column and uses the same rapidfuzz score.
