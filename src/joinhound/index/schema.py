# SPDX-License-Identifier: Apache-2.0

"""Apply the kg schema migrations."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from yoyo import get_backend, read_migrations

_MIGRATION_FILE = "0001.kg.sql"


def apply_schema(dsn: str) -> None:
    """Create the kg schema. A second call applies nothing new."""
    backend = get_backend(yoyo_uri(dsn))
    migrations = read_migrations(str(migrations_directory()))
    try:
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
    finally:
        backend.connection.close()


def yoyo_uri(dsn: str) -> str:
    """Return a yoyo URL that uses psycopg 3 for a libpq URL."""
    parsed = urlsplit(dsn)
    if parsed.scheme in {"postgresql", "postgres"}:
        return urlunsplit(parsed._replace(scheme="postgresql+psycopg"))
    if parsed.scheme == "postgresql+psycopg":
        return dsn
    raise ValueError(f"Unsupported database URL scheme {parsed.scheme!r}")


def migrations_directory() -> Path:
    """Locate the SQL migrations in an installed wheel or a source checkout."""
    packaged = Path(__file__).resolve().parents[1] / "migrations"
    if (packaged / _MIGRATION_FILE).is_file():
        return packaged
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "migrations"
        if (candidate / _MIGRATION_FILE).is_file():
            return candidate
    raise FileNotFoundError("kg migrations were not found")
