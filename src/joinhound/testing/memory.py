# SPDX-License-Identifier: Apache-2.0

"""In-memory sources used to exercise connector contracts."""

from collections.abc import Iterator

from joinhound.core.models import (
    AccessInfo,
    Capabilities,
    CollectionInfo,
    ColumnStats,
    Cursor,
    DeclaredFK,
    DocRef,
    Match,
    Record,
)
from joinhound.core.uri import PgUri, S3Uri, build_uri


class MemoryTabularSource:
    """A small relational source stored in process memory."""

    def __init__(
        self,
        rows: dict[str, list[dict[str, object]]],
        foreign_keys: list[DeclaredFK] | None = None,
    ) -> None:
        self.capabilities = Capabilities(
            pushdown_exact=True,
            pushdown_normalized=False,
            incremental=True,
            acl=False,
        )
        self._rows = rows
        self._foreign_keys = foreign_keys or []

    def list_collections(self) -> list[CollectionInfo]:
        """Return one collection for each stored table."""
        return [CollectionInfo(collection_id=name, name=name, kind="table") for name in self._rows]

    def declared_links(self) -> list[DeclaredFK]:
        """Return the foreign keys supplied to the source."""
        return list(self._foreign_keys)

    def column_stats(self, coll: str) -> list[ColumnStats]:
        """Return one statistic entry for each column present in the sample rows."""
        columns = {column for row in self._rows[coll] for column in row}
        return [ColumnStats(column_name=column, type_class="text") for column in sorted(columns)]

    def sample(self, coll: str, columns: list[str], n: int) -> list[dict[str, object]]:
        """Return the first n rows, restricted to the requested columns."""
        return [{column: row.get(column) for column in columns} for row in self._rows[coll][:n]]

    def fetch_by_keys(self, coll: str, keys: list[dict[str, object]]) -> list[Record]:
        """Return rows whose id matches one of the requested keys."""
        wanted = {key["id"] for key in keys}
        return [
            Record(
                uri=build_uri(PgUri("memory", "public", coll, {"id": row["id"]})),
                collection_id=coll,
                pk={"id": row["id"]},
                values=dict(row),
            )
            for row in self._rows[coll]
            if row["id"] in wanted
        ]

    def find_values(
        self,
        coll: str,
        column: str,
        values: list[str],
        mode: str,
        normalize_sql: str | None = None,
        limit: int = 50,
    ) -> list[Match]:
        """Find exact column matches. Normalized search is not implemented."""
        del normalize_sql
        if mode != "exact":
            return []
        matches = [
            Match(pk={"id": row["id"]}, value=str(row[column]))
            for row in self._rows[coll]
            if str(row.get(column)) in values
        ]
        return matches[:limit]

    def scan_column(
        self,
        coll: str,
        column: str,
        since: Cursor | None,
    ) -> Iterator[tuple[dict[str, object], str]]:
        """Yield every column value. The cursor selects nothing new when it is set."""
        if since is not None:
            return
        for row in self._rows[coll]:
            yield {"id": row["id"]}, str(row.get(column, ""))


class MemoryDocumentSource:
    """A small document source stored in process memory."""

    def __init__(self, documents: dict[str, bytes], roles: list[str] | None = None) -> None:
        self.capabilities = Capabilities(
            pushdown_exact=False,
            pushdown_normalized=False,
            incremental=True,
            acl=True,
        )
        self._documents = documents
        self._roles = roles or []

    def list_collections(self) -> list[CollectionInfo]:
        """Return the single in-memory document collection."""
        return [CollectionInfo(collection_id="docs", name="docs", kind="documents")]

    def changes_since(self, coll: str, cursor: Cursor | None) -> Iterator[DocRef]:
        """Yield every document. A cursor means the caller has already seen them."""
        del coll
        if cursor is not None:
            return
        for name in self._documents:
            yield DocRef(uri=build_uri(S3Uri("memory", name)))

    def read(self, ref: DocRef) -> bytes:
        """Return the stored bytes for a document URI."""
        parsed = ref.uri.removeprefix("s3://memory/")
        return self._documents[parsed]

    def acl(self, ref: DocRef) -> AccessInfo | None:
        """Return the roles configured for the collection."""
        del ref
        return AccessInfo(roles=list(self._roles))
