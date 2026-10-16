# SPDX-License-Identifier: Apache-2.0

"""Command-line entry point."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import typer
import yaml

from joinhound import __version__
from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import PostgresSourceConfig, load_config
from joinhound.core.protocols import LinkMatcher, TabularSource
from joinhound.core.registry import load_plugins
from joinhound.engine.evaluate import precision_recall
from joinhound.formats.ossie import (
    ModelError,
    OssieFormat,
    apply_links,
    links_from_document,
    parse_document,
)
from joinhound.index.columns import save_column_profiles
from joinhound.index.links import ColumnLink, save_links, stored_links
from joinhound.index.model import model_links, model_text, store_model
from joinhound.index.schema import apply_schema
from joinhound.profiler.profile import propose_links
from joinhound.server import create_server, runtime_from_config

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


@app.command()
def profile(
    config: str = typer.Option(
        "joinhound.yaml",
        "--config",
        help="Path to the YAML configuration.",
    ),
    auto_approve: float | None = typer.Option(
        None,
        "--auto-approve",
        help="Approve proposals whose confidence is at least this value.",
    ),
) -> None:
    """Write column fingerprints and relationship proposals."""
    written = _profile_sources(Path(config), auto_approve)
    typer.echo(f"links {written}")


@app.command(name="import")
def import_(
    format_name: str = typer.Argument(help="Model format. Only ossie is supported."),
    path: str = typer.Argument(help="Ossie YAML or JSON file."),
    config: str = typer.Option(
        "joinhound.yaml",
        "--config",
        help="Path to the YAML configuration.",
    ),
) -> None:
    """Replace kg.links with the relationships in an Ossie model."""
    _require_ossie(format_name)
    try:
        written = _import_ossie(Path(config), Path(path))
    except ModelError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f"links {written}")


@app.command()
def export(
    format_name: str = typer.Argument(help="Model format. Only ossie is supported."),
    out: str = typer.Option(..., "--out", help="File to write."),
    config: str = typer.Option(
        "joinhound.yaml",
        "--config",
        help="Path to the YAML configuration.",
    ),
) -> None:
    """Write the stored Ossie model, including links changed since import."""
    _require_ossie(format_name)
    try:
        text = _export_ossie(Path(config))
    except ModelError as error:
        raise typer.BadParameter(str(error)) from error
    Path(out).write_text(text, encoding="utf-8")


@app.command()
def serve(
    config: str = typer.Option(
        "joinhound.yaml",
        "--config",
        help="Path to the YAML configuration.",
    ),
) -> None:
    """Serve get_context, expand, and get_record over MCP stdio."""
    settings = load_config(Path(config))
    if settings.server.transport != "stdio":
        raise typer.BadParameter("Only the stdio transport is available")
    create_server(runtime_from_config(settings)).run(transport="stdio")


def _require_ossie(format_name: str) -> None:
    if format_name != "ossie":
        raise typer.BadParameter("format must be ossie")


def _import_ossie(config_path: Path, model_path: Path) -> int:
    settings = load_config(config_path)
    text = model_path.read_text(encoding="utf-8")
    document = parse_document(text)
    drafts = links_from_document(document)
    store_model(settings.kg_database, text, [draft for draft in drafts if draft is not None])
    return len(drafts)


def _export_ossie(config_path: Path) -> str:
    settings = load_config(config_path)
    text = model_text(settings.kg_database)
    if text is None:
        raise ModelError("No Ossie model has been imported")
    document = parse_document(text)
    updated = apply_links(document, model_links(settings.kg_database))
    if updated == document:
        return text
    return OssieFormat().dump(yaml.safe_dump(updated))


def _profile_sources(config_path: Path, auto_approve: float | None) -> int:
    settings = load_config(config_path)
    approve_at = settings.profiler.auto_approve if auto_approve is None else auto_approve
    written = 0
    for name, source_config in settings.sources.items():
        if not isinstance(source_config, PostgresSourceConfig):
            continue
        source = PostgresSource(name, source_config)
        with source:
            profiles, drafts = propose_links(source, settings.profiler, _matchers(source))
        save_column_profiles(settings.kg_database, name, profiles)
        save_links(settings.kg_database, drafts, approve_at)
        written += len(drafts)
    return written


def _matchers(source: TabularSource) -> Mapping[str, LinkMatcher]:
    plugins = load_plugins("joinhound.matchers")
    matchers: dict[str, LinkMatcher] = {}
    for name in ("declared_fk", "exact"):
        factory = plugins[name]
        if not callable(factory):
            raise TypeError(f"Matcher {name} is not callable")
        matchers[name] = cast(LinkMatcher, factory(source))
    return matchers


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
