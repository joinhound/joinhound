# SPDX-License-Identifier: Apache-2.0

"""Extension points. Implementations are registered through entry points."""

from collections.abc import Iterator
from typing import Literal, Protocol

from joinhound.core.models import (
    AccessInfo,
    Candidate,
    Capabilities,
    CollectionInfo,
    CollectionProfile,
    ColumnProfile,
    ColumnStats,
    Cursor,
    DeclaredFK,
    DocRef,
    JudgeVerdict,
    Link,
    Match,
    ProfileContext,
    QueryContext,
    Record,
)


class TabularSource(Protocol):
    """A read-only source of relational collections."""

    capabilities: Capabilities

    def list_collections(self) -> list[CollectionInfo]:
        """Return the tables and views visible to the configured role."""

    def declared_links(self) -> list[DeclaredFK]:
        """Return foreign keys declared by the source catalog."""

    def column_stats(self, coll: str) -> list[ColumnStats]:
        """Return catalog statistics for the columns of one collection."""

    def sample(self, coll: str, columns: list[str], n: int) -> list[dict[str, object]]:
        """Return up to n sampled rows containing the requested columns."""

    def fetch_by_keys(self, coll: str, keys: list[dict[str, object]]) -> list[Record]:
        """Return the rows identified by the given primary keys."""

    def find_values(
        self,
        coll: str,
        column: str,
        values: list[str],
        mode: Literal["exact", "normalized"],
        normalize_sql: str | None = None,
        limit: int = 50,
    ) -> list[Match]:
        """Find rows whose column matches the given values."""

    def scan_column(
        self,
        coll: str,
        column: str,
        since: Cursor | None,
    ) -> Iterator[tuple[dict[str, object], str]]:
        """Yield primary keys and column values changed since the cursor."""


class DocumentSource(Protocol):
    """A read-only source of document collections."""

    capabilities: Capabilities

    def list_collections(self) -> list[CollectionInfo]:
        """Return the configured document prefixes."""

    def changes_since(self, coll: str, cursor: Cursor | None) -> Iterator[DocRef]:
        """Yield documents created or changed since the cursor."""

    def read(self, ref: DocRef) -> bytes:
        """Return the bytes of one document."""

    def acl(self, ref: DocRef) -> AccessInfo | None:
        """Return the access rule for one document, when the source provides it."""


class DocumentParser(Protocol):
    """Extract text and coordinates from a document of one MIME type."""

    mime_types: tuple[str, ...]

    def parse(self, data: bytes) -> list[str]:
        """Return the text blocks found in the document."""


class OcrEngine(Protocol):
    """Read text from a page image."""

    def recognize(self, image: bytes) -> str:
        """Return the text recognized in the image."""


class Judge(Protocol):
    """Decide whether a proposed relationship is meaningful."""

    def review(self, candidate: Candidate) -> JudgeVerdict | None:
        """Review one candidate. A disabled judge returns no decision."""


class Embedder(Protocol):
    """Create vectors for text."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector for each input text."""


class ModelFormat(Protocol):
    """Import and export a semantic model."""

    def load(self, text: str) -> str:
        """Validate model text and return its canonical form."""

    def dump(self, text: str) -> str:
        """Serialize a model without dropping unknown fields."""


class CatalogSource(Protocol):
    """Read column descriptions and sensitivity tags from an external catalog."""

    def column_descriptions(self) -> dict[str, str]:
        """Return descriptions keyed by collection and column."""


class LinkMatcher(Protocol):
    """Find a relationship during profiling and resolve it during a query."""

    match_type: str

    def discover(
        self,
        src: ColumnProfile,
        dst: ColumnProfile | CollectionProfile,
        ctx: ProfileContext,
    ) -> Candidate | None:
        """Return a candidate relationship, or nothing when this type does not apply."""

    def resolve(self, link: Link, values: list[str], ctx: QueryContext) -> list[Match]:
        """Find records related to the given values through one stored rule."""


class KgStore(Protocol):
    """Persistence for metadata and indexes. It does not store record pairs."""

    def links(self) -> list[Link]:
        """Return the stored relationship rules."""


class AclResolver(Protocol):
    """Decide which roles may read a document."""

    def roles_for(self, ref: DocRef) -> AccessInfo:
        """Return the roles allowed to read the document."""


class AuthProvider(Protocol):
    """Authenticate a caller of the MCP server."""

    def authenticate(self, token: str) -> bool:
        """Return whether the presented credential is accepted."""
