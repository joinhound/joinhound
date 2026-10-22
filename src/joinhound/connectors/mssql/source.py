# SPDX-License-Identifier: Apache-2.0

"""Read-only Microsoft SQL Server source."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal, cast
from urllib.parse import unquote, urlsplit

import pymssql

from joinhound.core.config import MssqlSourceConfig
from joinhound.core.models import (
    Capabilities,
    CollectionInfo,
    ColumnStats,
    Cursor,
    DeclaredFK,
    Match,
    Record,
    as_record,
)
from joinhound.core.uri import MssqlUri, build_uri

_TYPE_CLASSES = {
    "bigint": "int",
    "bit": "bool",
    "date": "date",
    "datetime": "date",
    "datetime2": "date",
    "decimal": "numeric",
    "float": "numeric",
    "int": "int",
    "money": "numeric",
    "numeric": "numeric",
    "real": "numeric",
    "smalldatetime": "date",
    "smallint": "int",
    "smallmoney": "numeric",
    "time": "date",
    "tinyint": "int",
}


class SourceError(RuntimeError):
    """The SQL Server source could not complete a read."""


class MssqlSource:
    """One SQL Server database, opened read-only."""

    def __init__(self, name: str, config: MssqlSourceConfig) -> None:
        self.name = name
        self.config = config
        self.capabilities = Capabilities(
            pushdown_exact=True,
            pushdown_normalized=False,
            incremental=False,
            acl=False,
        )
        self.scan_cursor: Cursor | None = None
        host, port, user, password, database = _parse_dsn(config.dsn)
        timeout = max(1, config.statement_timeout_ms // 1000)
        self._connection = pymssql.connect(
            server=host,
            port=str(port),
            user=user,
            password=password,
            database=database,
            timeout=timeout,
            login_timeout=timeout,
            as_dict=True,
            appname="joinhound",
            read_only=True,
            autocommit=True,
        )

    def close(self) -> None:
        """Close the connection."""
        self._connection.close()

    def __enter__(self) -> MssqlSource:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def list_collections(self) -> list[CollectionInfo]:
        """Return base tables in the configured schemas."""
        placeholders = ", ".join("%s" for _ in self.config.schemas)
        rows = self._query(
            f"""
            SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS table_name
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA IN ({placeholders})
            ORDER BY TABLE_SCHEMA, TABLE_NAME
            """,
            tuple(self.config.schemas),
        )
        return [
            CollectionInfo(
                collection_id=_collection_id(
                    self.name, str(row["schema_name"]), str(row["table_name"])
                ),
                name=str(row["table_name"]),
                kind="table",
            )
            for row in rows
            if not self._excluded(str(row["schema_name"]), str(row["table_name"]))
        ]

    def declared_links(self) -> list[DeclaredFK]:
        """Return foreign keys declared in the catalog."""
        rows = self._query(
            """
            SELECT
              fk.name AS fk_name,
              OBJECT_SCHEMA_NAME(fkc.parent_object_id) AS src_schema,
              OBJECT_NAME(fkc.parent_object_id) AS src_table,
              pc.name AS src_column,
              OBJECT_SCHEMA_NAME(fkc.referenced_object_id) AS dst_schema,
              OBJECT_NAME(fkc.referenced_object_id) AS dst_table,
              rc.name AS dst_column
            FROM sys.foreign_keys AS fk
            JOIN sys.foreign_key_columns AS fkc
              ON fkc.constraint_object_id = fk.object_id
            JOIN sys.columns AS pc
              ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
            JOIN sys.columns AS rc
              ON rc.object_id = fkc.referenced_object_id
             AND rc.column_id = fkc.referenced_column_id
            ORDER BY fk.name, fkc.constraint_column_id
            """,
            (),
        )
        grouped: dict[str, DeclaredFK] = {}
        for row in rows:
            src_schema = str(row["src_schema"])
            src_table = str(row["src_table"])
            dst_schema = str(row["dst_schema"])
            dst_table = str(row["dst_table"])
            if src_schema not in self.config.schemas or dst_schema not in self.config.schemas:
                continue
            if self._excluded(src_schema, src_table) or self._excluded(dst_schema, dst_table):
                continue
            link = grouped.setdefault(
                str(row["fk_name"]),
                DeclaredFK(
                    src_collection=_collection_id(self.name, src_schema, src_table),
                    src_columns=[],
                    dst_collection=_collection_id(self.name, dst_schema, dst_table),
                    dst_columns=[],
                ),
            )
            link.src_columns.append(str(row["src_column"]))
            link.dst_columns.append(str(row["dst_column"]))
        return list(grouped.values())

    def column_stats(self, coll: str) -> list[ColumnStats]:
        """Return column names and coarse types. Distinct counts are left unset."""
        schema, table = self._location(coll)
        rows = self._query(
            """
            SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            (schema, table),
        )
        return [
            ColumnStats(
                column_name=str(row["column_name"]),
                type_class=_TYPE_CLASSES.get(str(row["data_type"]), "text"),
            )
            for row in rows
        ]

    def sample(self, coll: str, columns: list[str], n: int) -> list[dict[str, object]]:
        """Return up to n rows and the requested columns."""
        if n <= 0 or not columns:
            return []
        schema, table = self._location(coll)
        selected = ", ".join(_ident(column) for column in columns)
        rows = self._query(
            f"SELECT TOP (%s) {selected} FROM {_table(schema, table)}",
            (n,),
        )
        return [{str(key): _plain(value) for key, value in row.items()} for row in rows]

    def fetch_by_keys(self, coll: str, keys: list[dict[str, object]]) -> list[Record]:
        """Return the rows identified by the given keys."""
        if not keys:
            return []
        schema, table = self._location(coll)
        plan = self._primary_key(schema, table)
        clauses: list[str] = []
        params: list[object] = []
        for key in keys:
            parts = [f"{_ident(column)} = %s" for column in plan]
            clauses.append("(" + " AND ".join(parts) + ")")
            params.extend(key[column] for column in plan)
        where = " OR ".join(clauses)
        return self._records(coll, schema, table, plan, where, params, limit=None)

    def find_values(
        self,
        coll: str,
        column: str,
        values: list[str],
        mode: Literal["exact", "normalized"],
        normalize_sql: str | None = None,
        limit: int = 50,
    ) -> list[Match]:
        """Find rows whose column text equals one of the given values."""
        return [
            Match(
                pk=dict(record.pk),
                value="" if record.values.get(column) is None else str(record.values[column]),
            )
            for record in self.match_records(coll, column, values, mode, normalize_sql, limit)
        ]

    def match_records(
        self,
        coll: str,
        column: str,
        values: list[str],
        mode: Literal["exact", "normalized"],
        normalize_sql: str | None = None,
        limit: int = 50,
    ) -> list[Record]:
        """Return matching rows in one statement."""
        del normalize_sql
        if mode != "exact":
            raise SourceError("SQL Server normalized search is not pushed down")
        if not values or limit <= 0:
            return []
        schema, table = self._location(coll)
        plan = self._primary_key(schema, table)
        placeholders = ", ".join("%s" for _ in values)
        where = f"CONVERT(nvarchar(4000), {_ident(column)}) IN ({placeholders})"
        return self._records(coll, schema, table, plan, where, list(values), limit=limit)

    def scan_column(
        self,
        coll: str,
        column: str,
        since: Cursor | None,
    ) -> Iterator[tuple[dict[str, object], str]]:
        """Yield every key and column value. The cursor is ignored."""
        del since
        self.scan_cursor = None
        schema, table = self._location(coll)
        plan = self._primary_key(schema, table)
        for record in self._records(coll, schema, table, plan, "1 = 1", [], limit=None):
            raw = record.values.get(column)
            yield dict(record.pk), "" if raw is None else str(raw)

    def _records(
        self,
        coll: str,
        schema: str,
        table: str,
        plan: list[str],
        where: str,
        params: list[object],
        *,
        limit: int | None,
    ) -> list[Record]:
        top = "" if limit is None else "TOP (%s) "
        bound = () if limit is None else (limit,)
        rows = self._query(
            f"SELECT {top}* FROM {_table(schema, table)} WHERE {where}",
            bound + tuple(params),
        )
        records: list[Record] = []
        for row in rows:
            payload = {str(key): _plain(value) for key, value in row.items()}
            pk = {column: payload[column] for column in plan}
            records.append(
                as_record(
                    build_uri(MssqlUri(source=self.name, schema=schema, table=table, pk=pk)),
                    coll,
                    pk,
                    payload,
                )
            )
        return records

    def _primary_key(self, schema: str, table: str) -> list[str]:
        rows = self._query(
            """
            SELECT col.name AS column_name
            FROM sys.tables AS tab
            JOIN sys.schemas AS sch ON sch.schema_id = tab.schema_id
            JOIN sys.indexes AS idx
              ON idx.object_id = tab.object_id AND idx.is_primary_key = 1
            JOIN sys.index_columns AS ic
              ON ic.object_id = idx.object_id AND ic.index_id = idx.index_id
            JOIN sys.columns AS col
              ON col.object_id = ic.object_id AND col.column_id = ic.column_id
            WHERE sch.name = %s AND tab.name = %s
            ORDER BY ic.key_ordinal
            """,
            (schema, table),
        )
        columns = [str(row["column_name"]) for row in rows]
        if not columns:
            raise SourceError(f"{schema}.{table} has no primary key")
        return columns

    def _location(self, coll: str) -> tuple[str, str]:
        prefix = f"mssql://{self.name}/"
        if not coll.startswith(prefix):
            raise SourceError(f"Collection {coll} is not in source {self.name}")
        location = coll[len(prefix) :]
        if "." not in location:
            raise SourceError(f"Collection {coll} must contain schema.table")
        schema, table = location.split(".", 1)
        if (
            not schema
            or not table
            or schema not in self.config.schemas
            or self._excluded(schema, table)
        ):
            raise SourceError(f"Collection {coll} is not visible")
        return schema, table

    def _excluded(self, schema: str, table: str) -> bool:
        del schema
        return table in self.config.exclude_tables

    def _query(self, statement: str, params: tuple[object, ...]) -> list[dict[str, object]]:
        cursor = self._connection.cursor(as_dict=True)
        cursor.execute(statement, params)
        if cursor.description is None:
            return []
        return [cast(dict[str, object], row) for row in cursor.fetchall()]


def _collection_id(source: str, schema: str, table: str) -> str:
    return f"mssql://{source}/{schema}.{table}"


def _table(schema: str, table: str) -> str:
    return f"{_ident(schema)}.{_ident(table)}"


def _ident(name: str) -> str:
    if not name or any(character in name for character in "[]"):
        raise SourceError(f"Invalid SQL identifier: {name}")
    return f"[{name}]"


def _plain(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _parse_dsn(dsn: str) -> tuple[str, int, str, str, str]:
    parts = urlsplit(dsn)
    database = parts.path.lstrip("/")
    if (
        parts.scheme != "mssql"
        or not parts.hostname
        or not parts.username
        or parts.password is None
        or not database
    ):
        raise SourceError("MSSQL DSN must be mssql://user:password@host:port/database")
    return (
        parts.hostname,
        parts.port or 1433,
        unquote(parts.username),
        unquote(parts.password),
        database,
    )
