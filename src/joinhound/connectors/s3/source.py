# SPDX-License-Identifier: Apache-2.0

"""Read-only S3 document source."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from typing import Protocol, cast

from obstore.store import S3Store

from joinhound.core.config import S3SourceConfig
from joinhound.core.models import AccessInfo, Capabilities, CollectionInfo, Cursor, DocRef
from joinhound.core.uri import S3Uri, build_uri, parse_uri

logger = logging.getLogger(__name__)

_MAX_BYTES = 100 * 1024 * 1024
_ARCHIVES = (".zip", ".tar", ".tgz", ".gz", ".bz2", ".7z", ".rar")


class _Body(Protocol):
    def bytes(self) -> bytes:
        """Return the object body."""


class _Store(Protocol):
    def list(self, prefix: str | None = None) -> Iterator[Sequence[Mapping[str, object]]]:
        """Yield pages of object metadata."""

    def get(self, path: str) -> _Body:
        """Return an object whose bytes() method holds the body."""


class S3Source:
    """One S3 bucket prefix, read with obstore."""

    def __init__(self, name: str, config: S3SourceConfig, *, store: _Store | None = None) -> None:
        self.name = name
        self.config = config
        self.capabilities = Capabilities(
            pushdown_exact=False,
            pushdown_normalized=False,
            incremental=True,
            acl=True,
        )
        self._store = store if store is not None else _open_store(config)

    @property
    def collection_id(self) -> str:
        """Return the collection address, including the configured prefix."""
        prefix = self.config.prefix.strip("/")
        suffix = f"/{prefix}/" if prefix else "/"
        return f"s3://{self.name}{suffix}"

    def list_collections(self) -> list[CollectionInfo]:
        """Return the one document collection configured for this source."""
        return [CollectionInfo(collection_id=self.collection_id, name=self.name, kind="documents")]

    def changes_since(self, coll: str, cursor: Cursor | None) -> Iterator[DocRef]:
        """Yield objects whose ETag changed, and objects that disappeared."""
        if coll not in {self.name, self.collection_id}:
            raise ValueError(f"Unknown collection: {coll}")
        previous = _cursor_etags(cursor)
        seen: set[str] = set()
        for page in self._store.list(self.config.prefix or None):
            for meta in page:
                path = str(meta["path"])
                if not _kept(path, meta.get("size")):
                    continue
                seen.add(path)
                etag = _etag(meta.get("e_tag"))
                if previous is not None and previous.get(path) == etag:
                    continue
                yield DocRef(uri=_uri(self.name, path), etag=etag)
        if previous is None:
            return
        for path, etag in sorted(previous.items()):
            if path not in seen:
                yield DocRef(uri=_uri(self.name, path), etag=etag, deleted=True)

    def read(self, ref: DocRef) -> bytes:
        """Return the object bytes. The source never writes."""
        parsed = parse_uri(ref.uri)
        if not isinstance(parsed, S3Uri) or parsed.source != self.name:
            raise ValueError(f"Document is not in this source: {ref.uri}")
        body = cast(_Body, self._store.get(parsed.key))
        return bytes(body.bytes())

    def acl(self, ref: DocRef) -> AccessInfo | None:
        """Return the roles configured for the collection."""
        del ref
        return AccessInfo(roles=list(self.config.acl.roles))


def _open_store(config: S3SourceConfig) -> S3Store:
    endpoint = os.environ.get("AWS_ENDPOINT_URL") or os.environ.get("AWS_ENDPOINT_URL_S3")
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    options: dict[str, object] = {}
    if endpoint:
        options["endpoint"] = endpoint
        options["virtual_hosted_style_request"] = False
    if access_key and secret_key:
        options["access_key_id"] = access_key
        options["secret_access_key"] = secret_key
    client_options = {"allow_http": True} if endpoint and endpoint.startswith("http://") else None
    return S3Store(
        config.bucket,
        region=config.region or "us-east-1",
        client_options=client_options,
        **options,  # type: ignore[arg-type]
    )


def _cursor_etags(cursor: Cursor | None) -> dict[str, str] | None:
    if cursor is None:
        return None
    loaded = json.loads(cursor.value)
    if not isinstance(loaded, dict) or not isinstance(loaded.get("etags"), dict):
        raise ValueError("S3 cursor must be a JSON object with an etags map")
    return {str(path): str(etag) for path, etag in loaded["etags"].items()}


def _kept(path: str, size: object) -> bool:
    if path.lower().endswith(_ARCHIVES):
        logger.warning("Skipping archive %s", path)
        return False
    if isinstance(size, int) and size > _MAX_BYTES:
        logger.warning("Skipping %s: larger than 100 MB", path)
        return False
    return True


def _etag(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _uri(source: str, key: str) -> str:
    return build_uri(S3Uri(source=source, key=key))
