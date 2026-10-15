# SPDX-License-Identifier: Apache-2.0

"""Command-line entry point."""

from pathlib import Path

import typer

from joinhound import __version__
from joinhound.core.config import load_config
from joinhound.index.schema import apply_schema

app = typer.Typer(
    name="joinhound",
    help="Find and traverse hidden relationships across databases and documents.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"joinhound {__version__}")
        raise typer.Exit


@app.callback()
def callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Joinhound command-line interface."""


@app.command()
def init(
    config: str = typer.Option(
        "joinhound.yaml",
        "--config",
        help="Path to the YAML configuration.",
    ),
) -> None:
    """Create the kg schema."""
    apply_schema(load_config(Path(config)).kg_database)


if __name__ == "__main__":
    app()
