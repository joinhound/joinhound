# SPDX-License-Identifier: Apache-2.0

"""Command-line entry point."""

import json
from pathlib import Path

import typer

from joinhound import __version__
from joinhound.core.config import load_config
from joinhound.engine.evaluate import precision_recall
from joinhound.index.links import ColumnLink, stored_links
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


@app.command(name="eval")
def evaluate(
    config: str = typer.Option(
        "joinhound.yaml",
        "--config",
        help="Path to the YAML configuration.",
    ),
    gold: str = typer.Option(
        "tests/eval/gold/pagila_fk.json",
        "--gold",
        help="Foreign keys removed from the Pagila copy.",
    ),
) -> None:
    """Score kg.links against a gold set of foreign keys."""
    settings = load_config(Path(config))
    precision, recall = precision_recall(stored_links(settings.kg_database), _load_gold(gold))
    typer.echo(f"precision {precision:.3f}")
    typer.echo(f"recall {recall:.3f}")


def _load_gold(path: str) -> list[ColumnLink]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise typer.BadParameter("Gold file must be a JSON object")
    constraints = loaded.get("constraints")
    if not isinstance(constraints, list):
        raise typer.BadParameter("Gold file must contain a constraints list")
    links: list[ColumnLink] = []
    for item in constraints:
        if not isinstance(item, dict):
            raise typer.BadParameter("Each gold constraint must be an object")
        links.append(
            ColumnLink(
                src_collection=f"{item['schema']}.{item['table']}",
                src_columns=tuple(str(column) for column in item["columns"]),
                dst_collection=f"{item['ref_schema']}.{item['ref_table']}",
                dst_columns=tuple(str(column) for column in item["ref_columns"]),
            )
        )
    return links


if __name__ == "__main__":
    app()
