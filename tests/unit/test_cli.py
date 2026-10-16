# SPDX-License-Identifier: Apache-2.0

"""Tests for the command-line entry point."""

import re

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


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"joinhound {__version__}"
