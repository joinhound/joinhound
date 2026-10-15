# SPDX-License-Identifier: Apache-2.0

"""Source addresses used as provenance."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UriError(ValueError):
    """A source address cannot be parsed or built."""


@dataclass(frozen=True)
class PgUri:
    """Address of a PostgreSQL row, optionally narrowed to one column."""

    source: str
    schema: str
    table: str
    pk: Mapping[str, object]
    column: str | None = None
    unstable: bool = False
    row_hash: str | None = None


@dataclass(frozen=True)
class S3Uri:
    """Address of an S3 object or a located passage inside it."""

    source: str
    key: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None


SourceUri = PgUri | S3Uri


def parse_uri(value: str) -> SourceUri:
    """Parse a PostgreSQL or S3 provenance URI."""
    parts = urlsplit(value)
    if parts.scheme == "pg":
        return _parse_pg(parts.netloc, parts.path, parts.fragment)
    if parts.scheme == "s3":
        return _parse_s3(parts.netloc, parts.path, parts.fragment)
    raise UriError(f"Unsupported URI scheme: {parts.scheme or '(none)'}")


def build_uri(uri: SourceUri) -> str:
    """Build the canonical form of a provenance URI."""
    if isinstance(uri, PgUri):
        return _build_pg(uri)
    return _build_s3(uri)


def _parse_pg(source: str, path: str, fragment: str) -> PgUri:
    if not source:
        raise UriError("PostgreSQL URI is missing its source")
    location = path.lstrip("/")
    if "." not in location:
        raise UriError("PostgreSQL URI must contain schema.table")
    schema, table = location.split(".", 1)
    if not schema or not table:
        raise UriError("PostgreSQL URI must contain schema.table")
    params = dict(parse_qsl(fragment, keep_blank_values=True))
    if "pk" not in params:
        raise UriError("PostgreSQL URI is missing pk")
    return PgUri(
        source=source,
        schema=schema,
        table=table,
        pk=_json_object(params["pk"]),
        column=params.get("col"),
        unstable=params.get("unstable") == "true",
        row_hash=params.get("hash"),
    )


def _parse_s3(source: str, path: str, fragment: str) -> S3Uri:
    if not source:
        raise UriError("S3 URI is missing its source")
    key = path.lstrip("/")
    if not key:
        raise UriError("S3 URI is missing its key")
    params = dict(parse_qsl(fragment, keep_blank_values=True))
    page = int(params["page"]) if "page" in params else None
    bbox = _bbox(params["bbox"]) if "bbox" in params else None
    return S3Uri(source=source, key=key, page=page, bbox=bbox)


def _build_pg(uri: PgUri) -> str:
    query: dict[str, str] = {
        "pk": json.dumps(dict(uri.pk), sort_keys=True, separators=(",", ":")),
    }
    if uri.column is not None:
        query["col"] = uri.column
    if uri.unstable:
        query["unstable"] = "true"
    if uri.row_hash is not None:
        query["hash"] = uri.row_hash
    return urlunsplit(("pg", uri.source, f"/{uri.schema}.{uri.table}", "", urlencode(query)))


def _build_s3(uri: S3Uri) -> str:
    query: dict[str, str] = {}
    if uri.page is not None:
        query["page"] = str(uri.page)
    if uri.bbox is not None:
        query["bbox"] = ",".join(str(number) for number in uri.bbox)
    fragment = urlencode(query)
    return urlunsplit(("s3", uri.source, f"/{uri.key}", "", fragment))


def _json_object(value: str) -> dict[str, object]:
    try:
        parsed = cast(object, json.loads(value))
    except json.JSONDecodeError as error:
        raise UriError("pk must be a JSON object") from error
    if not isinstance(parsed, dict):
        raise UriError("pk must be a JSON object")
    return {str(key): cast(object, item) for key, item in parsed.items()}


def _bbox(value: str) -> tuple[float, float, float, float]:
    parts = value.split(",")
    if len(parts) != 4:
        raise UriError("bbox must contain four numbers")
    try:
        coordinates = tuple(float(part) for part in parts)
    except ValueError as error:
        raise UriError("bbox must contain four numbers") from error
    return cast(tuple[float, float, float, float], coordinates)
