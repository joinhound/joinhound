# SPDX-License-Identifier: Apache-2.0

"""Importing and exporting the TPC-DS Ossie model returns the same file."""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from testcontainers.community.postgres import PostgresContainer
from typer.testing import CliRunner

from joinhound.cli import app
from joinhound.index.schema import apply_schema

runner = CliRunner()
_TPC_DS = Path(__file__).parents[1] / "fixtures" / "tpcds_semantic_model.yaml"


def test_import_export_round_trip_is_identical(tmp_path: Path) -> None:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="joinhound",
        password="joinhound",
        dbname="joinhound",
        driver=None,
    ) as postgres:
        dsn = postgres.get_connection_url(driver=None)
        apply_schema(dsn)
        config = _write_config(tmp_path, dsn)
        imported = runner.invoke(app, ["import", "ossie", str(_TPC_DS), "--config", str(config)])
        assert imported.exit_code == 0, imported.output
        out = tmp_path / "exported.yaml"
        exported = runner.invoke(
            app,
            ["export", "ossie", "--out", str(out), "--config", str(config)],
        )

        assert exported.exit_code == 0, exported.output
        assert out.read_text(encoding="utf-8") == _TPC_DS.read_text(encoding="utf-8")
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT status, origin, match_type
                FROM kg.links
                """
            ).fetchall()
        assert len(rows) == 4
        assert {row["status"] for row in rows} == {"approved"}
        assert {row["origin"] for row in rows} == {"ossie_import"}
        assert {row["match_type"] for row in rows} == {"exact"}


def _write_config(directory: Path, dsn: str) -> Path:
    path = directory / "joinhound.yaml"
    path.write_text(
        "\n".join(
            [
                "mode: sidecar",
                f"kg_database: {dsn}",
                "sources: {}",
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
