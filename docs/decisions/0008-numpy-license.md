# 0008. Accept numpy's permissive license conjunction

## Context

The profiler uses `datasketch` for 128-permutation MinHash, as the specification names that library for containment search. Current datasketch releases depend on numpy. numpy declares `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`. BSD-3-Clause and MIT are already allowed. 0BSD, Zlib, and CC0-1.0 are permissive terms that are not in the base allow list.

## Decision

The license check accepts that exact declaration for numpy only. The library is used unmodified. Another package with the same declaration still fails.

## Alternatives

- Implement MinHash in the repository. That discards the library the specification names.
- Vendor numpy. That does not change the license obligation.
