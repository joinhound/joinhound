# SPDX-License-Identifier: Apache-2.0

"""Tests for the command-line entry point."""

import re
from pathlib import Path

from typer.testing import CliRunner

from joinhound import __version__
from joinhound.cli import app

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_help_exits_successfully() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "joinhound" in result.output


def test_profile_help_includes_auto_approve() -> None:
    result = runner.invoke(app, ["profile", "--help"])

    assert result.exit_code == 0
    # Rich styles each hyphenated segment, so the flag is split when color is on.
    assert "--auto-approve" in _ANSI.sub("", result.output)


def test_help_lists_serve() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "serve" in _ANSI.sub("", result.output)


def test_sync_with_no_document_source_prints_zero(tmp_path: Path) -> None:
    config = tmp_path / "joinhound.yaml"
    config.write_text(
        "\n".join(
            [
                "mode: sidecar",
                "kg_database: postgresql://joinhound@localhost/joinhound",
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

    result = runner.invoke(app, ["sync", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "documents 0\nvalues 0"


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"joinhound {__version__}"
