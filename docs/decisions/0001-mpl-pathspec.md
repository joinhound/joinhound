# 0001. Allow MPL-2.0 for pathspec

## Context

The license policy allows Apache-2.0, MIT, BSD, ISC, PostgreSQL, PSF, and LGPL used as an unmodified library. The specification also requires mypy. Current mypy releases depend on pathspec, whose declared license is MPL-2.0.

## Decision

The license check accepts pathspec's MPL-2.0 declaration. MPL-2.0 is file-level weak copyleft and applies only because mypy needs the library unchanged. Other MPL dependencies fail the check unless a later decision names them.

## Alternatives

- Drop mypy. This conflicts with the required strict type check for `core` and `engine`.
- Vendor pathspec. That adds maintenance without changing the license obligation.
