# SPDX-License-Identifier: Apache-2.0

"""Read-only Azure Blob document source."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator

from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient

from joinhound.core.config import AzureSourceConfig
from joinhound.core.models import AccessInfo, Capabilities, CollectionInfo, Cursor, DocRef
from joinhound.core.uri import AzureUri, build_uri, parse_uri

logger = logging.getLogger(__name__)

_MAX_BYTES = 100 * 1024 * 1024
_ARCHIVES = (".zip", ".tar", ".tgz", ".gz", ".bz2", ".7z", ".rar")


class SourceError(RuntimeError):
    """The Azure Blob source could not complete a read."""


class AzureSource:
    """One blob container, listed and downloaded. The source never writes."""

    def __init__(self, name: str, config: AzureSourceConfig) -> None:
        self.name = name
        self.config = config
        self.capabilities = Capabilities(
            pushdown_exact=False,
            pushdown_normalized=False,
            incremental=True,
            acl=True,
        )
        self._container = _open_client(config).get_container_client(config.container)

    @property
    def collection_id(self) -> str:
        """Return the collection address, including the configured prefix."""
        prefix = self.config.prefix.strip("/")
        suffix = f"/{prefix}/" if prefix else "/"
        return f"azure://{self.name}{suffix}"

    def list_collections(self) -> list[CollectionInfo]:
        """Return the one document collection configured for this source."""
        return [CollectionInfo(collection_id=self.collection_id, name=self.name, kind="documents")]

    def changes_since(self, coll: str, cursor: Cursor | None) -> Iterator[DocRef]:
        """Yield blobs whose etag changed, and blobs that disappeared."""
        if coll not in {self.name, self.collection_id}:
            raise ValueError(f"Unknown collection: {coll}")
        previous = _cursor_etags(cursor)
        seen: set[str] = set()
        prefix = self.config.prefix or None
        try:
            blobs = self._container.list_blobs(name_starts_with=prefix)
        except AzureError as error:
            raise SourceError("Azure Blob listing failed") from error
        for blob in blobs:
            path = blob.name
            if not _kept(path, blob.size):
                continue
            seen.add(path)
            etag = blob.etag
            if previous is not None and previous.get(path) == etag:
                continue
            yield DocRef(uri=_uri(self.name, path), etag=etag)
        if previous is None:
            return
        for path, etag in sorted(previous.items()):
            if path not in seen:
                yield DocRef(uri=_uri(self.name, path), etag=etag, deleted=True)

    def read(self, ref: DocRef) -> bytes:
        """Return the blob bytes. The source never writes."""
        parsed = parse_uri(ref.uri)
        if not isinstance(parsed, AzureUri) or parsed.source != self.name:
            raise ValueError(f"Document is not in this source: {ref.uri}")
        try:
            return bytes(self._container.download_blob(parsed.key).readall())
        except AzureError as error:
            raise SourceError(f"Azure Blob download failed: {parsed.key}") from error

    def acl(self, ref: DocRef) -> AccessInfo | None:
        """Return the roles configured for the collection."""
        del ref
        return AccessInfo(roles=list(self.config.acl.roles))


def _open_client(config: AzureSourceConfig) -> BlobServiceClient:
    connection = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    if connection:
        return BlobServiceClient.from_connection_string(connection)
    key = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY", "").strip()
    if config.account_url and key:
        return BlobServiceClient(config.account_url, credential=key)
    raise SourceError(
        "Set AZURE_STORAGE_CONNECTION_STRING, or account_url and AZURE_STORAGE_ACCOUNT_KEY"
    )


def _cursor_etags(cursor: Cursor | None) -> dict[str, str] | None:
    if cursor is None:
        return None
    loaded = json.loads(cursor.value)
    if not isinstance(loaded, dict) or not isinstance(loaded.get("etags"), dict):
        raise ValueError("Azure cursor must be a JSON object with an etags map")
    return {str(path): str(etag) for path, etag in loaded["etags"].items()}


def _kept(path: str, size: object) -> bool:
    if path.lower().endswith(_ARCHIVES):
        logger.warning("Skipping archive %s", path)
        return False
    if isinstance(size, int) and size > _MAX_BYTES:
        logger.warning("Skipping %s: larger than 100 MB", path)
        return False
    return True


def _uri(source: str, key: str) -> str:
    return build_uri(AzureUri(source=source, key=key))
