# 0004. Allow MPL-2.0 for certifi

## Context

T0.7 needs an integration test against PostgreSQL with pgvector. The specification names testcontainers for that. testcontainers depends on requests, which depends on certifi. certifi declares MPL-2.0, the same license already accepted for pathspec.

## Decision

The license check accepts certifi's MPL-2.0 declaration. The library is used unmodified. Any other MPL dependency still fails the check unless a decision names it.

## Alternatives

- Avoid testcontainers and talk to the compose database. That makes CI depend on a long-lived stack and conflicts with the specified test tool.
- Replace requests inside testcontainers. That means maintaining a fork.
