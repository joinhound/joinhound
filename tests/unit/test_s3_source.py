# SPDX-License-Identifier: Apache-2.0

"""ETag cursors, skips, and collection roles for the S3 source."""

import json
import logging

import pytest

from joinhound.connectors.s3 import S3Source
from joinhound.core.config import AclConfig, S3SourceConfig
from joinhound.core.models import Cursor


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def bytes(self) -> bytes:
        return self._payload


class _Store:
    def __init__(self, objects: dict[str, tuple[bytes, str, int]]) -> None:
        self.objects = objects

    def list(self, prefix: str | None = None) -> list[list[dict[str, object]]]:
        rows = []
        for path, (payload, etag, size) in self.objects.items():
            if prefix and not path.startswith(prefix):
                continue
            rows.append({"path": path, "e_tag": etag, "size": size, "body": payload})
        return [rows]

    def get(self, path: str) -> _Body:
        return _Body(self.objects[path][0])


def _source(store: _Store) -> S3Source:
    config = S3SourceConfig(
        type="s3",
        bucket="docs",
        prefix="",
        acl=AclConfig(roles=["legal"]),
    )
    return S3Source("docs", config, store=store)


def test_cursor_reports_a_changed_etag_and_a_removal() -> None:
    store = _Store({"notes.txt": (b"one", "a", 3), "old.txt": (b"old", "b", 3)})
    source = _source(store)
    first = list(source.changes_since("docs", None))
    assert {ref.uri for ref in first} == {
        "s3://docs/notes.txt",
        "s3://docs/old.txt",
    }
    cursor = Cursor(value=json.dumps({"etags": {"notes.txt": "a", "old.txt": "b"}}))
    store.objects = {"notes.txt": (b"two", "c", 3)}

    second = list(source.changes_since("docs", cursor))

    changed = [ref for ref in second if not ref.deleted]
    removed = [ref for ref in second if ref.deleted]
    assert [ref.uri for ref in changed] == ["s3://docs/notes.txt"]
    assert [ref.uri for ref in removed] == ["s3://docs/old.txt"]
    access = source.acl(changed[0])
    assert source.read(changed[0]) == b"two"
    assert access is not None
    assert access.roles == ["legal"]


def test_large_and_archive_objects_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    store = _Store(
        {
            "notes.txt": (b"ok", "a", 2),
            "bundle.zip": (b"zip", "b", 3),
            "huge.bin": (b"h", "c", 100 * 1024 * 1024 + 1),
        }
    )
    source = _source(store)
    with caplog.at_level(logging.WARNING):
        found = list(source.changes_since("docs", None))

    assert [ref.uri for ref in found] == ["s3://docs/notes.txt"]
