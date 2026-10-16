# SPDX-License-Identifier: Apache-2.0

"""A changed embedding model is refused until reindex is requested."""

import psycopg
from testcontainers.community.postgres import PostgresContainer

from joinhound.index.embedding_model import EmbeddingModelChanged, check_embedding_model
from joinhound.index.schema import apply_schema
from joinhound.llm.hashing import HashEmbedder
from joinhound.llm.openai_embedder import OpenAIEmbedder


def test_hash_vectors_match_identical_text() -> None:
    embedder = HashEmbedder(dim=128)
    first, second, other = embedder.embed(["Ada Lovelace", "Ada Lovelace", "WIDGET-8"])

    assert first == second
    assert sum(value * other_value for value, other_value in zip(first, other, strict=True)) < 0.8


def test_openai_embedder_uses_the_injected_client() -> None:
    class _Item:
        def __init__(self, embedding: list[float]) -> None:
            self.embedding = embedding

    class _Response:
        def __init__(self) -> None:
            self.data = [_Item([0.0, 1.0])]

    class _Embeddings:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs: object) -> _Response:
            self.calls += 1
            assert kwargs["model"] == "text-embedding-3-large"
            assert kwargs["input"] == ["Ada"]
            return _Response()

    class _Client:
        def __init__(self) -> None:
            self.embeddings = _Embeddings()

    client = _Client()
    vectors = OpenAIEmbedder(dim=2, client=client).embed(["Ada"])

    assert client.embeddings.calls == 1
    assert vectors == [[0.0, 1.0]]


def test_a_different_model_requires_reindex() -> None:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="joinhound",
        password="joinhound",
        dbname="joinhound",
        driver=None,
    ) as postgres:
        dsn = postgres.get_connection_url(driver=None)
        apply_schema(dsn)
        check_embedding_model(dsn, "joinhound-hash-v1", 1024, reindex=False)
        try:
            check_embedding_model(dsn, "text-embedding-3-large", 1024, reindex=False)
        except EmbeddingModelChanged as error:
            message = str(error)
        else:
            raise AssertionError("a model change was accepted")

        assert "joinhound sync --reindex" in message
        check_embedding_model(dsn, "text-embedding-3-large", 1024, reindex=True)
        with psycopg.connect(dsn) as connection:
            row = connection.execute("SELECT model FROM kg.embedding_model").fetchone()
        assert row == ("text-embedding-3-large",)
