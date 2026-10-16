# SPDX-License-Identifier: Apache-2.0

"""Remember which embedding model produced the stored vectors."""

from __future__ import annotations

import psycopg


class EmbeddingModelChanged(RuntimeError):
    """Stored vectors were built by a different model."""


def check_embedding_model(dsn: str, model: str, dim: int, *, reindex: bool) -> None:
    """Record the model, or refuse a change until the caller asks to reindex."""
    with psycopg.connect(dsn) as connection:
        present = connection.execute("SELECT to_regclass('kg.embedding_model')").fetchone()
        if present is None or present[0] is None:
            return
        row = connection.execute("SELECT model, dim FROM kg.embedding_model").fetchone()
        if row is None:
            _store(connection, model, dim)
            connection.commit()
            return
        stored_model, stored_dim = str(row[0]), int(row[1])
        if (stored_model, stored_dim) == (model, dim):
            return
        if not reindex:
            raise EmbeddingModelChanged(_message(stored_model, stored_dim, model, dim))
        connection.execute("DELETE FROM kg.embedding_model")
        connection.execute("UPDATE kg.chunks SET embedding = NULL")
        connection.execute("UPDATE kg.value_index SET embedding = NULL")
        _store(connection, model, dim)
        connection.commit()


def _store(connection: psycopg.Connection[tuple[object, ...]], model: str, dim: int) -> None:
    connection.execute(
        "INSERT INTO kg.embedding_model (model, dim) VALUES (%s, %s)",
        (model, dim),
    )


def _message(stored_model: str, stored_dim: int, model: str, dim: int) -> str:
    return (
        f"Stored embeddings use {stored_model} ({stored_dim}). "
        f"Configured model is {model} ({dim}). Run joinhound sync --reindex."
    )
