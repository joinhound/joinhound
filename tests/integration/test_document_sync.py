# SPDX-License-Identifier: Apache-2.0

"""Document sync replaces changed files and drops deleted ones."""

import json
from collections.abc import Iterator

import psycopg
from testcontainers.community.postgres import PostgresContainer

from joinhound.core.models import AccessInfo, Capabilities, CollectionInfo, Cursor, DocRef
from joinhound.index.documents import read_passages, sync_documents
from joinhound.index.schema import apply_schema
from joinhound.llm.none import NoneEmbedder
from joinhound.parsers import HtmlParser

_PARSER = HtmlParser()


class _Docs:
    def __init__(self) -> None:
        self.files: dict[str, tuple[str, bytes]] = {}
        self.capabilities = Capabilities(
            pushdown_exact=False,
            pushdown_normalized=False,
            incremental=True,
            acl=True,
        )

    def list_collections(self) -> list[CollectionInfo]:
        return [CollectionInfo(collection_id="s3://docs/", name="docs", kind="documents")]

    def changes_since(self, coll: str, cursor: Cursor | None) -> Iterator[DocRef]:
        del coll
        previous = None if cursor is None else json.loads(cursor.value)["etags"]
        seen: set[str] = set()
        for key, (etag, _content) in self.files.items():
            seen.add(key)
            if previous is not None and previous.get(key) == etag:
                continue
            yield DocRef(uri=f"s3://docs/{key}", etag=etag)
        if previous is None:
            return
        for key, etag in previous.items():
            if key not in seen:
                yield DocRef(uri=f"s3://docs/{key}", etag=str(etag), deleted=True)

    def read(self, ref: DocRef) -> bytes:
        key = ref.uri.removeprefix("s3://docs/")
        return self.files[key][1]

    def acl(self, ref: DocRef) -> AccessInfo:
        del ref
        return AccessInfo(roles=["legal"])


def test_changed_document_is_reindexed_and_deleted_document_is_removed() -> None:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="joinhound",
        password="joinhound",
        dbname="joinhound",
        driver=None,
    ) as postgres:
        dsn = postgres.get_connection_url(driver=None)
        apply_schema(dsn)
        source = _Docs()
        source.files["note.html"] = ("1", b"<p>alpha report</p>")
        source.files["keep.html"] = ("1", b"<p>keep this</p>")
        assert _sync(dsn, source) == 2

        source.files["note.html"] = ("2", b"<p>beta report</p>")
        assert _sync(dsn, source) == 1
        texts = _texts(dsn)
        assert "beta report" in texts
        assert "alpha report" not in texts
        assert "keep this" in texts

        del source.files["keep.html"]
        assert _sync(dsn, source) == 1
        remaining = _texts(dsn)
        assert "keep this" not in remaining
        assert "beta report" in remaining
        with psycopg.connect(dsn) as connection:
            row = connection.execute(
                "SELECT page, bbox, embedding, acl FROM kg.chunks JOIN kg.documents USING (doc_id)"
            ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert len(row[1]) == 4
        assert row[2] is not None
        assert row[3] == {"roles": ["legal"]}
        stored = read_passages(dsn)
        assert [passage.text for passage in stored] == ["beta report"]
        assert stored[0].roles == ("legal",)
        assert stored[0].page == 1


def _sync(dsn: str, source: _Docs) -> int:
    return sync_documents(
        dsn,
        "docs",
        source,
        NoneEmbedder(dim=1024),
        lambda mime, data: _PARSER.parse(data) if mime == "text/html" else [],
    )


def _texts(dsn: str) -> list[str]:
    with psycopg.connect(dsn) as connection:
        rows = connection.execute("SELECT text FROM kg.chunks ORDER BY text").fetchall()
    return [str(row[0]) for row in rows]
