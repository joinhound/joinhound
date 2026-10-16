# SPDX-License-Identifier: Apache-2.0

"""Read-only PostgreSQL source."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from joinhound.core.config import PostgresSourceConfig
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
from joinhound.core.uri import PgUri, build_uri

_SMALL_TABLE_ROWS = 10_000
_BLOCK_MODULUS = 32
_TYPE_CLASSES = {
    "bool": "bool",
    "bpchar": "text",
    "char": "text",
    "date": "date",
    "float4": "numeric",
    "float8": "numeric",
    "int2": "int",
    "int4": "int",
    "int8": "int",
    "money": "numeric",
    "name": "text",
    "numeric": "numeric",
    "text": "text",
    "time": "date",
    "timestamp": "date",
    "timestamptz": "date",
    "timetz": "date",
    "uuid": "uuid",
    "varchar": "text",
}


class SourceError(ValueError):
    """The PostgreSQL source cannot complete a read."""


@dataclass(frozen=True)
class KeyPlan:
    """How rows of one collection are addressed."""

    columns: tuple[str, ...]
    unstable: bool
    has_updated_at: bool


def type_class(type_name: str) -> str:
    """Map a PostgreSQL type name to a profiler type class."""
    return _TYPE_CLASSES.get(type_name, "text")


def distinct_estimate(n_distinct: float | None, row_estimate: float) -> float | None:
    """Turn a pg_stats n_distinct value into an estimated count."""
    if n_distinct is None:
        return None
    if n_distinct >= 0:
        return float(n_distinct)
    if row_estimate > 0:
        return float(-n_distinct * row_estimate)
    return None


class PostgresSource:
    """A read-only PostgreSQL database."""

    def __init__(self, name: str, config: PostgresSourceConfig) -> None:
        self.name = name
        self.capabilities = Capabilities(
            pushdown_exact=True,
            pushdown_normalized=True,
            incremental=True,
            acl=False,
        )
        self._schemas = list(config.schemas)
        self._exclude = set(config.exclude_tables)
        self._timeout_ms = config.statement_timeout_ms
        self.scan_cursor: Cursor | None = None
        self._pool: ConnectionPool[dict[str, object]] = ConnectionPool(
            config.dsn,
            min_size=1,
            max_size=4,
            open=True,
            kwargs={"autocommit": True, "row_factory": dict_row},
            configure=self._configure,
        )

    def close(self) -> None:
        """Close pooled connections."""
        self._pool.close()

    def __enter__(self) -> PostgresSource:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[dict[str, object]]]:
        """Borrow one read-only connection from the pool."""
        with self._pool.connection() as connection:
            yield connection

    def list_collections(self) -> list[CollectionInfo]:
        """Return tables, views, and materialized views in the configured schemas."""
        query = """
            SELECT namespace.nspname AS schema_name, relation.relname AS table_name
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE relation.relkind IN ('r', 'v', 'm', 'p')
              AND NOT relation.relispartition
              AND namespace.nspname = ANY(%s)
            ORDER BY namespace.nspname, relation.relname
        """
        with self.connection() as connection:
            rows = connection.execute(query, (self._schemas,)).fetchall()
        return [
            CollectionInfo(
                collection_id=_collection_id(
                    self.name,
                    str(row["schema_name"]),
                    str(row["table_name"]),
                ),
                name=str(row["table_name"]),
                kind="table",
            )
            for row in rows
            if not self._excluded(str(row["schema_name"]), str(row["table_name"]))
        ]

    def declared_links(self) -> list[DeclaredFK]:
        """Return foreign keys declared in the configured schemas."""
        query = """
            SELECT
              source_namespace.nspname AS source_schema,
              source_relation.relname AS source_table,
              target_namespace.nspname AS target_schema,
              target_relation.relname AS target_table,
              (
                SELECT array_agg(attribute.attname ORDER BY columns.ordinality)
                FROM unnest(constraint_.conkey) WITH ORDINALITY AS columns(attnum, ordinality)
                JOIN pg_attribute AS attribute
                  ON attribute.attrelid = source_relation.oid
                 AND attribute.attnum = columns.attnum
              ) AS source_columns,
              (
                SELECT array_agg(attribute.attname ORDER BY columns.ordinality)
                FROM unnest(constraint_.confkey) WITH ORDINALITY AS columns(attnum, ordinality)
                JOIN pg_attribute AS attribute
                  ON attribute.attrelid = target_relation.oid
                 AND attribute.attnum = columns.attnum
              ) AS target_columns
            FROM pg_constraint AS constraint_
            JOIN pg_class AS source_relation ON source_relation.oid = constraint_.conrelid
            JOIN pg_namespace AS source_namespace
              ON source_namespace.oid = source_relation.relnamespace
            JOIN pg_class AS target_relation ON target_relation.oid = constraint_.confrelid
            JOIN pg_namespace AS target_namespace
              ON target_namespace.oid = target_relation.relnamespace
            WHERE constraint_.contype = 'f'
              AND source_namespace.nspname = ANY(%s)
            ORDER BY source_namespace.nspname, source_relation.relname, constraint_.conname
        """
        with self.connection() as connection:
            rows = connection.execute(query, (self._schemas,)).fetchall()
        links: list[DeclaredFK] = []
        for row in rows:
            source_schema = str(row["source_schema"])
            source_table = str(row["source_table"])
            target_schema = str(row["target_schema"])
            target_table = str(row["target_table"])
            source_excluded = self._excluded(source_schema, source_table)
            target_excluded = self._excluded(target_schema, target_table)
            if source_excluded or target_excluded:
                continue
            if target_schema not in self._schemas:
                continue
            source_columns = cast(list[object], row["source_columns"])
            target_columns = cast(list[object], row["target_columns"])
            links.append(
                DeclaredFK(
                    src_collection=_collection_id(self.name, source_schema, source_table),
                    src_columns=[str(column) for column in source_columns],
                    dst_collection=_collection_id(self.name, target_schema, target_table),
                    dst_columns=[str(column) for column in target_columns],
                )
            )
        return links

    def column_stats(self, coll: str) -> list[ColumnStats]:
        """Return catalog statistics for one collection."""
        schema, table = self._location(coll)
        query = """
            SELECT
              attribute.attname AS column_name,
              type_.typname AS type_name,
              stats.n_distinct,
              stats.null_frac,
              relation.reltuples AS row_estimate
            FROM pg_attribute AS attribute
            JOIN pg_class AS relation ON relation.oid = attribute.attrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            JOIN pg_type AS type_ ON type_.oid = attribute.atttypid
            LEFT JOIN pg_stats AS stats
              ON stats.schemaname = namespace.nspname
             AND stats.tablename = relation.relname
             AND stats.attname = attribute.attname
            WHERE namespace.nspname = %s
              AND relation.relname = %s
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            ORDER BY attribute.attnum
        """
        with self.connection() as connection:
            rows = connection.execute(query, (schema, table)).fetchall()
        stats: list[ColumnStats] = []
        for row in rows:
            row_estimate = float(cast(float, row["row_estimate"]))
            n_distinct = cast(float | None, row["n_distinct"])
            null_ratio = cast(float | None, row["null_frac"])
            stats.append(
                ColumnStats(
                    column_name=str(row["column_name"]),
                    type_class=type_class(str(row["type_name"])),
                    n_distinct=distinct_estimate(n_distinct, row_estimate),
                    null_ratio=None if null_ratio is None else float(null_ratio),
                )
            )
        return stats

    def sample(self, coll: str, columns: list[str], n: int) -> list[dict[str, object]]:
        """Return up to n rows, sampling large tables and reading small ones."""
        schema, table = self._location(coll)
        plan = self._key_plan(schema, table)
        estimate = self._row_estimate(schema, table)
        if estimate <= 0 or estimate <= _SMALL_TABLE_ROWS:
            rows = self._query_rows(
                schema,
                table,
                plan,
                sql.SQL("TRUE"),
                [],
                order=not plan.unstable,
                limit=n,
            )
        else:
            percent = min(100.0, max(1.0, (n / estimate) * 100 * 5))
            rows = self._query_rows(
                schema,
                table,
                plan,
                sql.SQL("TRUE"),
                [],
                order=False,
                limit=n,
                sample_percent=percent,
            )
        return [{column: _payload(row)[column] for column in columns} for row in rows]

    def fetch_by_keys(self, coll: str, keys: list[dict[str, object]]) -> list[Record]:
        """Return the rows identified by the given keys."""
        if not keys:
            return []
        schema, table = self._location(coll)
        plan = self._key_plan(schema, table)
        clauses: list[sql.Composable] = []
        params: list[object] = []
        for key in keys:
            if plan.unstable:
                clauses.append(sql.SQL("t.ctid = %s::tid"))
                params.append(key["ctid"])
                continue
            parts = [
                sql.SQL("{} = %s").format(sql.Identifier("t", column)) for column in plan.columns
            ]
            clauses.append(sql.SQL("({})").format(sql.SQL(" AND ").join(parts)))
            params.extend(key[column] for column in plan.columns)
        where = sql.SQL(" OR ").join(clauses)
        return self._query_records(
            coll,
            schema,
            table,
            plan,
            where,
            params,
            order=False,
            limit=None,
        )

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
        """Return matching rows in one statement. Used when kg shares this database."""
        schema, table = self._location(coll)
        plan = self._key_plan(schema, table)
        if mode == "exact":
            where = sql.SQL("{}::text = ANY(%s)").format(sql.Identifier("t", column))
        elif normalize_sql is None:
            raise SourceError("normalized search requires normalize_sql")
        else:
            where = sql.SQL("({}) = ANY(%s)").format(sql.SQL(normalize_sql))
        return self._query_records(
            coll,
            schema,
            table,
            plan,
            where,
            [values],
            order=False,
            limit=limit,
        )

    def scan_column(
        self,
        coll: str,
        column: str,
        since: Cursor | None,
    ) -> Iterator[tuple[dict[str, object], str]]:
        """Yield keys and column values changed since the cursor.

        A table with ``updated_at`` yields rows newer than the cursor. Otherwise
        rows are grouped by a hash of the primary key, and only a group whose
        hash changed is read again. ``scan_cursor`` is the position to store.
        """
        self.scan_cursor = None
        schema, table = self._location(coll)
        plan = self._key_plan(schema, table)
        if plan.has_updated_at:
            yield from self._scan_updated(coll, schema, table, plan, column, since)
            return
        if plan.unstable:
            yield from self._scan_replaced(coll, schema, table, plan, column, since)
            return
        yield from self._scan_blocks(coll, schema, table, plan, column, since)

    def _scan_updated(
        self,
        coll: str,
        schema: str,
        table: str,
        plan: KeyPlan,
        column: str,
        since: Cursor | None,
    ) -> Iterator[tuple[dict[str, object], str]]:
        where, params = self._since(plan, since)
        if where is None:
            return
        stamp = self._max_updated_at(schema, table)
        if stamp is not None:
            self.scan_cursor = Cursor(value=stamp)
        elif since is not None:
            self.scan_cursor = since
        yield from self._yield_column(coll, schema, table, plan, column, where, params)

    def _scan_blocks(
        self,
        coll: str,
        schema: str,
        table: str,
        plan: KeyPlan,
        column: str,
        since: Cursor | None,
    ) -> Iterator[tuple[dict[str, object], str]]:
        digests = self._block_digests(schema, table, plan, column)
        self.scan_cursor = Cursor(value=_block_payload(_BLOCK_MODULUS, digests))
        previous = _stored_blocks(since)
        if previous is not None and previous == digests:
            return
        changed = set(digests) if previous is None else _changed_blocks(previous, digests)
        if not changed:
            return
        if previous is None:
            where: sql.Composable = sql.SQL("TRUE")
            params: list[object] = []
        else:
            where = sql.SQL("{} = ANY(%s)").format(_block_sql(plan))
            params = [sorted(int(block) for block in changed)]
        yield from self._yield_column(coll, schema, table, plan, column, where, params)

    def _scan_replaced(
        self,
        coll: str,
        schema: str,
        table: str,
        plan: KeyPlan,
        column: str,
        since: Cursor | None,
    ) -> Iterator[tuple[dict[str, object], str]]:
        digest = self._table_digest(schema, table, plan, column)
        self.scan_cursor = Cursor(value=_block_payload(0, {"0": digest}))
        if since is not None and since.value == self.scan_cursor.value:
            return
        yield from self._yield_column(coll, schema, table, plan, column, sql.SQL("TRUE"), [])

    def _yield_column(
        self,
        coll: str,
        schema: str,
        table: str,
        plan: KeyPlan,
        column: str,
        where: sql.Composable,
        params: list[object],
    ) -> Iterator[tuple[dict[str, object], str]]:
        for record in self._query_records(
            coll, schema, table, plan, where, params, order=True, limit=None
        ):
            value = record.values.get(column)
            yield dict(record.pk), "" if value is None else str(value)

    def _max_updated_at(self, schema: str, table: str) -> str | None:
        statement = sql.SQL("SELECT max(t.updated_at)::text AS stamp FROM {}.{} AS t").format(
            sql.Identifier(schema),
            sql.Identifier(table),
        )
        with self.connection() as connection:
            row = connection.execute(statement).fetchone()
        if row is None or row["stamp"] is None:
            return None
        return str(row["stamp"])

    def _block_digests(
        self,
        schema: str,
        table: str,
        plan: KeyPlan,
        column: str,
    ) -> dict[str, str]:
        statement = sql.SQL(
            """
            SELECT block::text AS block,
                   md5(string_agg(
                     pk_text || chr(31) || coalesce(value, ''),
                     chr(10) ORDER BY pk_text
                   )) AS digest
            FROM (
              SELECT {block} AS block, ({pk})::text AS pk_text, {value}::text AS value
              FROM {relation} AS t
            ) AS rows
            GROUP BY block
            """
        ).format(
            block=_block_sql(plan),
            pk=_pk_json(plan),
            value=sql.Identifier("t", column),
            relation=_relation(schema, table),
        )
        with self.connection() as connection:
            rows = connection.execute(statement).fetchall()
        return {str(row["block"]): str(row["digest"]) for row in rows if row["digest"] is not None}

    def _table_digest(self, schema: str, table: str, plan: KeyPlan, column: str) -> str:
        statement = sql.SQL(
            """
            SELECT coalesce(md5(string_agg(
                     pk_text || chr(31) || coalesce(value, ''),
                     chr(10) ORDER BY pk_text
                   )), '') AS digest
            FROM (
              SELECT ({pk})::text AS pk_text, {value}::text AS value
              FROM {relation} AS t
            ) AS rows
            """
        ).format(
            pk=_pk_json(plan),
            value=sql.Identifier("t", column),
            relation=_relation(schema, table),
        )
        with self.connection() as connection:
            row = connection.execute(statement).fetchone()
        if row is None or row["digest"] is None:
            return ""
        return str(row["digest"])

    def _configure(self, connection: psycopg.Connection[dict[str, object]]) -> None:
        connection.execute(
            sql.SQL("SET statement_timeout TO {}").format(sql.Literal(self._timeout_ms))
        )
        connection.execute("SET application_name TO 'joinhound'")
        connection.execute("SET default_transaction_read_only TO on")

    def _location(self, coll: str) -> tuple[str, str]:
        prefix = f"pg://{self.name}/"
        if not coll.startswith(prefix):
            raise SourceError(f"Collection {coll} is not in source {self.name}")
        location = coll[len(prefix) :]
        if "." not in location:
            raise SourceError(f"Collection {coll} must contain schema.table")
        schema, table = location.split(".", 1)
        if not schema or not table or self._excluded(schema, table) or schema not in self._schemas:
            raise SourceError(f"Collection {coll} is not visible")
        return schema, table

    def _excluded(self, schema: str, table: str) -> bool:
        return table in self._exclude or f"{schema}.{table}" in self._exclude

    def _key_plan(self, schema: str, table: str) -> KeyPlan:
        with self.connection() as connection:
            return select_key(connection, schema, table)

    def _row_estimate(self, schema: str, table: str) -> float:
        query = """
            SELECT relation.reltuples
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = %s AND relation.relname = %s
        """
        with self.connection() as connection:
            row = connection.execute(query, (schema, table)).fetchone()
        if row is None:
            raise SourceError(f"Collection {schema}.{table} does not exist")
        return float(cast(float, row["reltuples"]))

    def _since(
        self,
        plan: KeyPlan,
        since: Cursor | None,
    ) -> tuple[sql.Composable, list[object]] | tuple[None, list[object]]:
        if since is None:
            return sql.SQL("TRUE"), []
        if plan.has_updated_at:
            return sql.SQL("t.updated_at > %s"), [since.value]
        if plan.unstable:
            return None, []
        try:
            parsed = cast(object, json.loads(since.value))
        except json.JSONDecodeError as error:
            raise SourceError("scan cursor must be a JSON object") from error
        if not isinstance(parsed, dict):
            raise SourceError("scan cursor must be a JSON object")
        cursor = {str(key): cast(object, value) for key, value in parsed.items()}
        compared = sql.SQL("({}) > ({})").format(
            sql.SQL(", ").join(sql.Identifier("t", column) for column in plan.columns),
            sql.SQL(", ").join(sql.Placeholder() for _ in plan.columns),
        )
        return compared, [cursor[column] for column in plan.columns]

    def _query_records(
        self,
        coll: str,
        schema: str,
        table: str,
        plan: KeyPlan,
        where: sql.Composable,
        params: list[object],
        *,
        order: bool,
        limit: int | None,
    ) -> list[Record]:
        rows = self._query_rows(schema, table, plan, where, params, order=order, limit=limit)
        records: list[Record] = []
        for row in rows:
            payload = _payload(row)
            if plan.unstable:
                pk: dict[str, object] = {"ctid": row["ctid"]}
                row_hash = str(row["row_hash"])
            else:
                pk = {column: payload[column] for column in plan.columns}
                row_hash = None
            records.append(
                as_record(
                    build_uri(
                        PgUri(
                            source=self.name,
                            schema=schema,
                            table=table,
                            pk=pk,
                            unstable=plan.unstable,
                            row_hash=row_hash,
                        )
                    ),
                    coll,
                    pk,
                    payload,
                )
            )
        return records

    def _query_rows(
        self,
        schema: str,
        table: str,
        plan: KeyPlan,
        where: sql.Composable,
        params: list[object],
        *,
        order: bool,
        limit: int | None,
        sample_percent: float | None = None,
    ) -> list[dict[str, object]]:
        fields = [sql.SQL("to_jsonb(t)::text AS row_json")]
        if plan.unstable:
            fields.append(sql.SQL("t.ctid::text AS ctid"))
            fields.append(sql.SQL("md5(to_jsonb(t)::text) AS row_hash"))
        relation = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
        if sample_percent is None:
            from_clause = sql.SQL("{} AS t").format(relation)
        else:
            from_clause = sql.SQL("{} TABLESAMPLE SYSTEM ({}) AS t").format(
                relation,
                sql.Literal(sample_percent),
            )
        order_sql = sql.SQL("")
        if order:
            order_columns = (
                [sql.SQL("t.ctid")]
                if plan.unstable
                else [sql.Identifier("t", column) for column in plan.columns]
            )
            order_sql = sql.SQL(" ORDER BY {}").format(sql.SQL(", ").join(order_columns))
        if limit is None:
            limit_sql = sql.SQL("")
        else:
            limit_sql = sql.SQL(" LIMIT {}").format(sql.Literal(limit))
        statement = sql.SQL("SELECT {} FROM {} WHERE {}{}{}").format(
            sql.SQL(", ").join(fields),
            from_clause,
            where,
            order_sql,
            limit_sql,
        )
        with self.connection() as connection:
            return list(connection.execute(statement, params).fetchall())


def _relation(schema: str, table: str) -> sql.Composable:
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))


def _pk_json(plan: KeyPlan) -> sql.Composable:
    parts: list[sql.Composable] = []
    for column in plan.columns:
        parts.append(sql.Literal(column))
        parts.append(sql.Identifier("t", column))
    return sql.SQL("jsonb_build_object({})").format(sql.SQL(", ").join(parts))


def _block_sql(plan: KeyPlan) -> sql.Composable:
    return sql.SQL("mod(abs(hashtext(({})::text)::bigint), {})").format(
        _pk_json(plan),
        sql.Literal(_BLOCK_MODULUS),
    )


def _block_payload(modulus: int, blocks: dict[str, str]) -> str:
    return json.dumps({"modulus": modulus, "blocks": blocks}, sort_keys=True)


def _stored_blocks(since: Cursor | None) -> dict[str, str] | None:
    if since is None:
        return None
    try:
        parsed = cast(object, json.loads(since.value))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or "blocks" not in parsed:
        return None
    blocks = parsed["blocks"]
    if not isinstance(blocks, dict):
        return None
    return {str(key): str(value) for key, value in blocks.items()}


def _changed_blocks(previous: dict[str, str], current: dict[str, str]) -> set[str]:
    names = set(previous) | set(current)
    return {name for name in names if previous.get(name) != current.get(name)}


def select_key(
    connection: psycopg.Connection[dict[str, object]],
    schema: str,
    table: str,
) -> KeyPlan:
    """Choose a primary key, else a unique NOT NULL index, else ctid."""
    primary = _index_columns(connection, schema, table, primary=True)
    columns = primary[0] if primary else ()
    unstable = False
    if not columns:
        unique = _index_columns(connection, schema, table, primary=False)
        if unique:
            columns = unique[0]
        else:
            columns = ("ctid",)
            unstable = True
    updated = connection.execute(
        """
        SELECT 1
        FROM pg_attribute AS attribute
        JOIN pg_class AS relation ON relation.oid = attribute.attrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_type AS type_ ON type_.oid = attribute.atttypid
        WHERE namespace.nspname = %s
          AND relation.relname = %s
          AND attribute.attname = 'updated_at'
          AND type_.typname IN ('timestamp', 'timestamptz')
          AND NOT attribute.attisdropped
        """,
        (schema, table),
    ).fetchone()
    return KeyPlan(columns=columns, unstable=unstable, has_updated_at=updated is not None)


def _index_columns(
    connection: psycopg.Connection[dict[str, object]],
    schema: str,
    table: str,
    *,
    primary: bool,
) -> list[tuple[str, ...]]:
    query = """
        SELECT array_agg(attribute.attname ORDER BY columns.ordinality) AS columns
        FROM pg_index AS index
        JOIN pg_class AS relation ON relation.oid = index.indrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN unnest(index.indkey) WITH ORDINALITY AS columns(attnum, ordinality)
          ON columns.attnum > 0
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = relation.oid
         AND attribute.attnum = columns.attnum
        WHERE namespace.nspname = %s
          AND relation.relname = %s
          AND index.indisvalid
          AND index.indpred IS NULL
          AND NOT (0 = ANY (index.indkey))
          AND index.indisprimary = %s
          AND (%s OR index.indisunique)
        GROUP BY index.indexrelid
        HAVING bool_and(attribute.attnotnull)
        ORDER BY count(*) , array_agg(attribute.attname ORDER BY columns.ordinality)::text
    """
    rows = connection.execute(query, (schema, table, primary, primary)).fetchall()
    return [tuple(str(column) for column in cast(list[object], row["columns"])) for row in rows]


def _collection_id(source: str, schema: str, table: str) -> str:
    return f"pg://{source}/{schema}.{table}"


def _payload(row: dict[str, object]) -> dict[str, object]:
    parsed = cast(object, json.loads(str(row["row_json"])))
    if not isinstance(parsed, dict):
        raise SourceError("PostgreSQL row payload must be an object")
    return {str(key): cast(object, value) for key, value in parsed.items()}
