# SPDX-License-Identifier: Apache-2.0

"""Index document collections into kg.documents and kg.chunks."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import PurePosixPath

import psycopg
from psycopg.types.json import Json

from joinhound.core.models import Cursor, DocRef, IndexedPassage, TextBlock
from joinhound.core.protocols import DocumentSource, Embedder
from joinhound.core.uri import S3Uri, build_uri, parse_uri
from joinhound.index.chunks import chunk_blocks, normalize_blocks

logger = logging.getLogger(__name__)

_BATCH = 64
_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
}

Parse = Callable[[str, bytes], list[TextBlock]]


def sync_documents(
    dsn: str,
    source_name: str,
    source: DocumentSource,
    embedder: Embedder,
    parse: Parse,
    *,
    force: bool = False,
) -> int:
    """Index documents that changed since the stored ETags. Return how many were visited."""
    visited = 0
    with psycopg.connect(dsn) as connection:
        for collection in source.list_collections():
            if collection.kind != "documents":
                continue
            _ensure_collection(connection, source_name, collection.collection_id)
            stored = _stored(connection, collection.collection_id)
            cursor = None if force else _cursor(stored)
            for ref in source.changes_since(collection.collection_id, cursor):
                with connection.transaction():
                    _apply(connection, collection.collection_id, source, embedder, parse, ref)
                visited += 1
            connection.execute(
                "UPDATE kg.collections SET synced_at = now() WHERE collection_id = %s",
                (collection.collection_id,),
            )
        connection.commit()
    return visited


def _apply(
    connection: psycopg.Connection[tuple[object, ...]],
    collection_id: str,
    source: DocumentSource,
    embedder: Embedder,
    parse: Parse,
    ref: DocRef,
) -> None:
    connection.execute("DELETE FROM kg.documents WHERE doc_id = %s", (ref.uri,))
    if ref.deleted:
        return
    mime = _mime(ref.uri)
    passages: list[TextBlock] = []
    if mime is None:
        logger.warning("Skipping %s: unsupported document type", ref.uri)
    else:
        passages = chunk_blocks(normalize_blocks(parse(mime, source.read(ref))))
    access = source.acl(ref)
    roles = list(access.roles) if access is not None else []
    connection.execute(
        """
        INSERT INTO kg.documents (doc_id, collection_id, etag, mime, acl, parsed_at)
        VALUES (%s, %s, %s, %s, %s, now())
        """,
        (ref.uri, collection_id, ref.etag, mime, Json({"roles": roles})),
    )
    for passage, vector in zip(passages, _embed(embedder, passages), strict=True):
        connection.execute(
            """
            INSERT INTO kg.chunks (doc_id, page, bbox, text, embedding)
            VALUES (%s, %s, %s, %s, %s::vector)
            """,
            (ref.uri, passage.page, list(passage.bbox), passage.text, _vector(vector)),
        )


def _embed(embedder: Embedder, passages: list[TextBlock]) -> list[list[float]]:
    vectors: list[list[float]] = []
    texts = [passage.text for passage in passages]
    for offset in range(0, len(texts), _BATCH):
        vectors.extend(embedder.embed(texts[offset : offset + _BATCH]))
    if len(vectors) != len(texts):
        raise ValueError("Embedder returned a different number of vectors than texts")
    return vectors


def _ensure_collection(
    connection: psycopg.Connection[tuple[object, ...]],
    source_name: str,
    collection_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO kg.sources (source_id, kind, config)
        VALUES (%s, 's3', %s)
        ON CONFLICT (source_id) DO NOTHING
        """,
        (source_name, Json({"type": "s3"})),
    )
    connection.execute(
        """
        INSERT INTO kg.collections (collection_id, source_id, kind)
        VALUES (%s, %s, 'documents')
        ON CONFLICT (collection_id) DO NOTHING
        """,
        (collection_id, source_name),
    )


def _stored(
    connection: psycopg.Connection[tuple[object, ...]],
    collection_id: str,
) -> list[tuple[str, str]]:
    rows = connection.execute(
        "SELECT doc_id, etag FROM kg.documents WHERE collection_id = %s",
        (collection_id,),
    ).fetchall()
    return [(str(row[0]), "" if row[1] is None else str(row[1])) for row in rows]


def read_passages(dsn: str) -> list[IndexedPassage]:
    """Return the fragments stored for the query engine."""
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            """
            SELECT d.doc_id, d.collection_id, d.acl, c.page, c.bbox, c.text, c.embedding::text
            FROM kg.chunks AS c
            JOIN kg.documents AS d ON d.doc_id = c.doc_id
            ORDER BY d.doc_id, c.chunk_id
            """
        ).fetchall()
    passages: list[IndexedPassage] = []
    for doc_id, collection_id, acl, page, bbox, text, embedding in rows:
        box = tuple(float(value) for value in bbox)
        passages.append(
            IndexedPassage(
                uri=_passage_uri(str(doc_id), int(page), box),
                collection_id=str(collection_id),
                text=str(text),
                page=int(page),
                bbox=box,
                roles=_roles(acl),
                embedding=_embedding(embedding),
            )
        )
    return passages


def _passage_uri(doc_id: str, page: int, bbox: tuple[float, ...]) -> str:
    parsed = parse_uri(doc_id)
    if not isinstance(parsed, S3Uri) or len(bbox) != 4:
        return doc_id
    box = (bbox[0], bbox[1], bbox[2], bbox[3])
    return build_uri(S3Uri(parsed.source, parsed.key, page=page, bbox=box))


def _roles(acl: object) -> tuple[str, ...]:
    if not isinstance(acl, dict):
        return ()
    roles = acl.get("roles")
    if not isinstance(roles, list):
        return ()
    return tuple(str(role) for role in roles)


def _embedding(value: object) -> tuple[float, ...] | None:
    if not isinstance(value, str) or not value.startswith("["):
        return None
    body = value.strip("[]").strip()
    if not body:
        return None
    return tuple(float(part) for part in body.split(","))


def _cursor(stored: list[tuple[str, str]]) -> Cursor | None:
    etags: dict[str, str] = {}
    for uri, etag in stored:
        parsed = parse_uri(uri)
        if isinstance(parsed, S3Uri):
            etags[parsed.key] = etag
    if not etags:
        return None
    return Cursor(value=json.dumps({"etags": etags}, sort_keys=True))


def _mime(uri: str) -> str | None:
    parsed = parse_uri(uri)
    if not isinstance(parsed, S3Uri):
        return None
    return _MIME.get(PurePosixPath(parsed.key).suffix.lower())


def _vector(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"
