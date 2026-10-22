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
class MssqlUri:
    """Address of a SQL Server row."""

    source: str
    schema: str
    table: str
    pk: Mapping[str, object]


@dataclass(frozen=True)
class S3Uri:
    """Address of an S3 object or a located passage inside it."""

    source: str
    key: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class AzureUri:
    """Address of an Azure Blob or a located passage inside it."""

    source: str
    key: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None


SourceUri = PgUri | MssqlUri | S3Uri | AzureUri


def parse_uri(value: str) -> SourceUri:
    """Parse a provenance URI."""
    parts = urlsplit(value)
    if parts.scheme == "pg":
        return _parse_pg(parts.netloc, parts.path, parts.fragment)
    if parts.scheme == "mssql":
        return _parse_mssql(parts.netloc, parts.path, parts.fragment)
    if parts.scheme == "s3":
        return _parse_s3(parts.netloc, parts.path, parts.fragment)
    if parts.scheme == "azure":
        return _parse_azure(parts.netloc, parts.path, parts.fragment)
    raise UriError(f"Unsupported URI scheme: {parts.scheme or '(none)'}")


def build_uri(uri: SourceUri) -> str:
    """Build the canonical form of a provenance URI."""
    if isinstance(uri, PgUri):
        return _build_pg(uri)
    if isinstance(uri, MssqlUri):
        return _build_mssql(uri)
    if isinstance(uri, AzureUri):
        return _build_azure(uri)
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


def _parse_mssql(source: str, path: str, fragment: str) -> MssqlUri:
    if not source:
        raise UriError("SQL Server URI is missing its source")
    location = path.lstrip("/")
    if "." not in location:
        raise UriError("SQL Server URI must contain schema.table")
    schema, table = location.split(".", 1)
    if not schema or not table:
        raise UriError("SQL Server URI must contain schema.table")
    params = dict(parse_qsl(fragment, keep_blank_values=True))
    if "pk" not in params:
        raise UriError("SQL Server URI is missing pk")
    return MssqlUri(source=source, schema=schema, table=table, pk=_json_object(params["pk"]))


def _build_mssql(uri: MssqlUri) -> str:
    fragment = urlencode(
        {"pk": json.dumps(dict(uri.pk), sort_keys=True, separators=(",", ":"), default=str)}
    )
    return urlunsplit(("mssql", uri.source, f"/{uri.schema}.{uri.table}", "", fragment))


def _parse_s3(source: str, path: str, fragment: str) -> S3Uri:
    key, page, bbox = _object_parts(source, path, fragment, "S3")
    return S3Uri(source=source, key=key, page=page, bbox=bbox)


def _parse_azure(source: str, path: str, fragment: str) -> AzureUri:
    key, page, bbox = _object_parts(source, path, fragment, "Azure")
    return AzureUri(source=source, key=key, page=page, bbox=bbox)


def _object_parts(
    source: str,
    path: str,
    fragment: str,
    label: str,
) -> tuple[str, int | None, tuple[float, float, float, float] | None]:
    if not source:
        raise UriError(f"{label} URI is missing its source")
    key = path.lstrip("/")
    if not key:
        raise UriError(f"{label} URI is missing its key")
    params = dict(parse_qsl(fragment, keep_blank_values=True))
    page = int(params["page"]) if "page" in params else None
    bbox = _bbox(params["bbox"]) if "bbox" in params else None
    return key, page, bbox


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
    return _build_object("s3", uri.source, uri.key, uri.page, uri.bbox)


def _build_azure(uri: AzureUri) -> str:
    return _build_object("azure", uri.source, uri.key, uri.page, uri.bbox)


def _build_object(
    scheme: str,
    source: str,
    key: str,
    page: int | None,
    bbox: tuple[float, float, float, float] | None,
) -> str:
    query: dict[str, str] = {}
    if page is not None:
        query["page"] = str(page)
    if bbox is not None:
        query["bbox"] = ",".join(str(number) for number in bbox)
    return urlunsplit((scheme, source, f"/{key}", "", urlencode(query)))


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
