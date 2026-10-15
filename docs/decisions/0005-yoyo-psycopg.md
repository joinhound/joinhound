# 0005. Apply kg migrations with yoyo and psycopg 3

## Context

The specification allows Alembic or SQL files applied with yoyo-migrations. The kg schema is fixed SQL, including `vector(1024)`. yoyo's `postgresql://` backend imports psycopg2. The project already depends on psycopg 3, which is LGPL and used unmodified. Configuration stores a normal libpq URL in `kg_database`.

The SQL files live in `migrations/` at the repository root, as the layout in the specification shows. An installed `joinhound init` still has to find them.

## Decision

`joinhound init` applies `migrations/*.sql` with yoyo. A `postgresql://` or `postgres://` URL is rewritten to `postgresql+psycopg://` so yoyo uses psycopg 3. The wheel copies those SQL files into `joinhound/migrations`.

## Alternatives

- Alembic. The schema does not need Python migrations.
- Add psycopg2 so yoyo's default backend works. That is a second driver for the same database.
