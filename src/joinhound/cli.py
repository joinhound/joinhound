# SPDX-License-Identifier: Apache-2.0

"""Command-line entry point."""

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import typer
import yaml

from joinhound import __version__
from joinhound.connectors.postgres import PostgresSource
from joinhound.connectors.s3 import S3Source
from joinhound.core.config import AppConfig, PostgresSourceConfig, S3SourceConfig, load_config
from joinhound.core.models import LinkDraft, TextBlock
from joinhound.core.protocols import DocumentParser, Embedder, Judge, LinkMatcher, TabularSource
from joinhound.core.registry import load_plugins
from joinhound.engine.evaluate import precision_recall
from joinhound.engine.questions import load_questions, score_questions
from joinhound.formats.ossie import (
    ModelError,
    OssieFormat,
    apply_links,
    links_from_document,
    parse_document,
)
from joinhound.index.columns import save_column_profiles
from joinhound.index.documents import read_passages, sync_documents
from joinhound.index.embedding_model import EmbeddingModelChanged, check_embedding_model
from joinhound.index.links import ColumnLink, save_links, stored_links
from joinhound.index.model import model_links, model_text, store_model
from joinhound.index.schema import apply_schema
from joinhound.index.values import sync_values
from joinhound.llm.none import NoneEmbedder
from joinhound.profiler.profile import link_id, propose_links
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
    questions: str | None = typer.Option(
        None,
        "--questions",
        help="Questions with the record URIs an answer must cite.",
    ),
) -> None:
    """Score kg.links, or score get_context when --questions is set."""
    settings = load_config(Path(config))
    if questions is not None:
        _print_question_scores(settings, questions)
        return
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


@app.command()
def sync(
    config: str = typer.Option(
        "joinhound.yaml",
        "--config",
        help="Path to the YAML configuration.",
    ),
    reindex: bool = typer.Option(
        False,
        "--reindex",
        help="Rebuild stored vectors after an embedding model change.",
    ),
) -> None:
    """Index changed documents and approved fuzzy or semantic column values."""
    settings = load_config(Path(config))
    if settings.sources:
        try:
            check_embedding_model(
                settings.kg_database,
                settings.embeddings.model,
                settings.embeddings.dim,
                reindex=reindex,
            )
        except EmbeddingModelChanged as error:
            raise typer.BadParameter(str(error)) from error
    documents, values = _sync_sources(settings, force=reindex)
    typer.echo(f"documents {documents}")
    typer.echo(f"values {values}")


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
            profiles, drafts = propose_links(
                source,
                settings.profiler,
                _matchers(source, settings.kg_database, _embedder(settings)),
                _judge(settings),
            )
        save_column_profiles(settings.kg_database, name, profiles)
        save_links(settings.kg_database, drafts, approve_at)
        written += len(drafts)
    return written


def _sync_sources(settings: AppConfig, *, force: bool = False) -> tuple[int, int]:
    parsers = _document_parsers()
    embedder = _embedder(settings)
    documents = 0
    values = 0
    for name, source_config in settings.sources.items():
        if isinstance(source_config, S3SourceConfig):
            documents += sync_documents(
                settings.kg_database,
                name,
                S3Source(name, source_config),
                embedder,
                lambda mime, data: _parse(parsers, mime, data),
                force=force,
            )
        elif isinstance(source_config, PostgresSourceConfig):
            source = PostgresSource(name, source_config)
            with source:
                values += sync_values(
                    settings.kg_database,
                    name,
                    source,
                    embedder,
                    force=force,
                )
    return documents, values


def _parse(parsers: Mapping[str, DocumentParser], mime: str, data: bytes) -> list[TextBlock]:
    parser = parsers.get(mime)
    if parser is None:
        return []
    return parser.parse(data)


def _document_parsers() -> dict[str, DocumentParser]:
    ocr = _ocr_engine()
    found: dict[str, DocumentParser] = {}
    for factory in load_plugins("joinhound.parsers").values():
        if not callable(factory):
            continue
        try:
            parser = cast(DocumentParser, factory(ocr=ocr))
        except TypeError:
            parser = cast(DocumentParser, factory())
        for mime in parser.mime_types:
            found[mime] = parser
    return found


def _ocr_engine() -> object | None:
    if shutil.which("tesseract") is None:
        return None
    factory = load_plugins("joinhound.ocr").get("tesseract")
    if not callable(factory):
        return None
    return factory()


def _embedder(settings: AppConfig) -> Embedder:
    factory = load_plugins("joinhound.embedders").get(settings.embeddings.provider)
    if not callable(factory):
        raise typer.BadParameter(f"Unknown embeddings provider: {settings.embeddings.provider}")
    if settings.embeddings.provider == "openai":
        return cast(
            Embedder,
            factory(
                dim=settings.embeddings.dim,
                model=settings.embeddings.model,
                base_url=settings.embeddings.base_url,
                api_key=settings.embeddings.api_key,
            ),
        )
    if settings.embeddings.provider == "local":
        return cast(
            Embedder,
            factory(dim=settings.embeddings.dim, model=settings.embeddings.model),
        )
    return cast(Embedder, factory(dim=settings.embeddings.dim))


def _judge(settings: AppConfig) -> Judge:
    factory = load_plugins("joinhound.judges").get(settings.judge.provider)
    if not callable(factory):
        raise typer.BadParameter(f"Unknown judge provider: {settings.judge.provider}")
    if settings.judge.provider == "none":
        return cast(Judge, factory())
    return cast(
        Judge,
        factory(
            base_url=settings.judge.base_url,
            api_key=settings.judge.api_key,
            model=settings.judge.model,
            redact=settings.judge.redact,
            sensitive_columns=settings.judge.sensitive_columns,
            dsn=settings.kg_database,
        ),
    )


def _matchers(
    source: TabularSource,
    index_dsn: str | None = None,
    embedder: Embedder | None = None,
) -> Mapping[str, LinkMatcher]:
    plugins = load_plugins("joinhound.matchers")
    matchers: dict[str, LinkMatcher] = {}
    vectors = embedder or NoneEmbedder()
    for name in ("declared_fk", "exact", "normalized", "fuzzy", "semantic"):
        factory = plugins[name]
        if not callable(factory):
            raise TypeError(f"Matcher {name} is not callable")
        if name == "fuzzy":
            matchers[name] = cast(LinkMatcher, factory(source, index_dsn))
            continue
        if name == "semantic":
            matchers[name] = cast(LinkMatcher, factory(source, vectors, index_dsn))
            continue
        matchers[name] = cast(LinkMatcher, factory(source))
    return matchers


def _print_question_scores(settings: AppConfig, path: str) -> None:
    questions = load_questions(Path(path))
    for name, source_config in settings.sources.items():
        if not isinstance(source_config, PostgresSourceConfig):
            continue
        source = PostgresSource(name, source_config)
        with source:
            report = score_questions(
                questions,
                source,
                _declared_drafts(source),
                _matchers(source, settings.kg_database, _embedder(settings)),
                settings.engine,
                passages=read_passages(settings.kg_database),
            )
        typer.echo(f"context_precision {report.precision:.3f}")
        typer.echo(f"context_recall {report.recall:.3f}")
        typer.echo(f"context_p50_ms {report.latency_ms(50)}")
        typer.echo(f"context_p95_ms {report.latency_ms(95)}")


def _declared_drafts(source: TabularSource) -> list[LinkDraft]:
    drafts: list[LinkDraft] = []
    for foreign_key in source.declared_links():
        if len(foreign_key.src_columns) != 1 or len(foreign_key.dst_columns) != 1:
            continue
        src_column = foreign_key.src_columns[0]
        dst_column = foreign_key.dst_columns[0]
        drafts.append(
            LinkDraft(
                link_id=link_id(
                    foreign_key.src_collection,
                    src_column,
                    foreign_key.dst_collection,
                    dst_column,
                ),
                src_collection=foreign_key.src_collection,
                src_column=src_column,
                dst_collection=foreign_key.dst_collection,
                dst_column=dst_column,
                match_type="declared_fk",
                origin="catalog_fk",
                confidence=1.0,
                status="approved",
                cardinality="N:1",
            )
        )
    return drafts


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
