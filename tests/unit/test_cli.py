# SPDX-License-Identifier: Apache-2.0

"""Tests for the command-line entry point."""

from typer.testing import CliRunner

from joinhound import __version__
from joinhound.cli import app

runner = CliRunner()


def test_help_exits_successfully() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "joinhound" in result.output


def test_profile_help_includes_auto_approve() -> None:
    result = runner.invoke(app, ["profile", "--help"])

    assert result.exit_code == 0
    assert "--auto-approve" in result.output


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"joinhound {__version__}"
