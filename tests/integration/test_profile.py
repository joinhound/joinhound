# SPDX-License-Identifier: Apache-2.0

"""joinhound profile writes kg.links once and leaves approved rows alone."""

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from testcontainers.community.postgres import PostgresContainer
from typer.testing import CliRunner

from joinhound.cli import app
from joinhound.index.schema import apply_schema

runner = CliRunner()
_ROWS = 25


def test_profile_is_stable_and_preserves_approved_links(tmp_path: Path) -> None:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="joinhound",
        password="joinhound",
        dbname="joinhound",
        driver=None,
    ) as postgres:
        kg_dsn = postgres.get_connection_url(driver=None)
        shop_dsn = _replace_database(kg_dsn, "shop")
        _create_database(kg_dsn, "shop")
        _load_shop(shop_dsn)
        apply_schema(kg_dsn)
        config = _write_config(tmp_path, kg_dsn, shop_dsn)

        first = runner.invoke(app, ["profile", "--config", str(config)])
        assert first.exit_code == 0, first.output
        before = _links(kg_dsn)
        declared = _one(before, "declared_fk", "public.orders.customer_id__")
        email = _one(before, "exact", "public.orders.email__")
        assert declared["status"] == "approved"
        assert declared["confidence"] == 1.0
        assert declared["origin"] == "catalog_fk"
        assert email["status"] == "proposed"
        assert float(email["evidence"]["containment"]) >= 0.5
        assert email["evidence"]["matches"]

        _mark_approved(kg_dsn, str(declared["link_id"]))
        _clear_evidence(kg_dsn, str(email["link_id"]))
        second = runner.invoke(app, ["profile", "--config", str(config)])
        assert second.exit_code == 0, second.output
        refreshed = _links(kg_dsn)
        assert len(refreshed) == len(before)
        kept = _one(refreshed, "declared_fk", "public.orders.customer_id__")
        revised = _one(refreshed, "exact", "public.orders.email__")
        assert kept["confidence"] == 0.25
        assert kept["rationale"] == "kept"
        assert kept["status"] == "approved"
        assert float(revised["evidence"]["containment"]) >= 0.5
        assert revised["status"] == "proposed"

        approved = runner.invoke(
            app,
            ["profile", "--config", str(config), "--auto-approve", "0.9"],
        )
        assert approved.exit_code == 0, approved.output
        final = _links(kg_dsn)
        assert len(final) == len(before)
        assert _one(final, "declared_fk", "public.orders.customer_id__")["confidence"] == 0.25
        assert _one(final, "exact", "public.orders.email__")["status"] == "approved"


def _write_config(directory: Path, kg_dsn: str, shop_dsn: str) -> Path:
    path = directory / "joinhound.yaml"
    path.write_text(
        "\n".join(
            [
                "mode: sidecar",
                f"kg_database: {kg_dsn}",
                "sources:",
                "  shop:",
                "    type: postgres",
                f"    dsn: {shop_dsn}",
                "    schemas: [public]",
                "embeddings:",
                "  provider: none",
                "  model: none",
                "  dim: 1024",
                "judge:",
                "  provider: none",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _links(dsn: str) -> list[dict[str, object]]:
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT link_id, src_column, match_type, origin, status, confidence,
                   rationale, evidence
            FROM kg.links
            ORDER BY link_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _one(rows: list[dict[str, object]], match_type: str, prefix: str) -> dict[str, object]:
    matches = [
        row
        for row in rows
        if row["match_type"] == match_type and str(row["link_id"]).startswith(prefix)
    ]
    assert len(matches) == 1, rows
    return matches[0]


def _mark_approved(dsn: str, link_id: str) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            UPDATE kg.links
            SET confidence = 0.25, rationale = 'kept'
            WHERE link_id = %s
            """,
            (link_id,),
        )
        connection.commit()


def _clear_evidence(dsn: str, link_id: str) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE kg.links SET evidence = '{}'::jsonb WHERE link_id = %s",
            (link_id,),
        )
        connection.commit()


def _load_shop(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE TABLE customers (
              id int PRIMARY KEY,
              email text NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE orders (
              id int PRIMARY KEY,
              customer_id int NOT NULL REFERENCES customers (id),
              email text NOT NULL
            )
            """
        )
        for number in range(1, _ROWS + 1):
            email = f"user{number}@example.com"
            connection.execute(
                "INSERT INTO customers (id, email) VALUES (%s, %s)",
                (number, email),
            )
            connection.execute(
                "INSERT INTO orders (id, customer_id, email) VALUES (%s, %s, %s)",
                (number, number, email),
            )


def _create_database(dsn: str, name: str) -> None:
    admin = _replace_database(dsn, "postgres")
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _replace_database(dsn: str, name: str) -> str:
    parsed = urlsplit(dsn)
    return urlunsplit(parsed._replace(path=f"/{name}"))
