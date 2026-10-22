# Plugins

A new source, parser, matcher, judge, or embedder is a class plus an entry point. The core package does not import it. The process loads it by group name.

| Group | What the object does |
| --- | --- |
| `joinhound.connectors` | `TabularSource` or `DocumentSource` |
| `joinhound.parsers` | `DocumentParser` for one MIME type |
| `joinhound.ocr` | `OcrEngine` |
| `joinhound.matchers` | `LinkMatcher` |
| `joinhound.judges` | `Judge` |
| `joinhound.embedders` | `Embedder` |
| `joinhound.model_formats` | `ModelFormat` |
| `joinhound.auth` | bearer-token check |

Register it in `pyproject.toml`:

```toml
[project.entry-points."joinhound.connectors"]
example = "example_connector:ExampleSource"
```

The class lives in its own package. It may import `joinhound.core`. It does not import `joinhound.engine`, `joinhound.server`, or another connector.

## A read-only source

Implement the methods on `TabularSource` or `DocumentSource` in `joinhound.core.protocols`. Set `capabilities` honestly. `pushdown_exact` means `find_values` can compare values in the source. A document source yields changes, reads bytes, and reports an ACL.

The connection string is a new `type` on the source configuration. Adding that type is a small change in `joinhound.core.config` because the YAML tag is user-visible. The implementation itself stays outside `core`.

Customer sources are read-only. Do not create schemas, extensions, or triggers there, and do not store pairs of records.

## A matcher

`discover` proposes a column pair from samples. `resolve` finds destination rows for values the engine already has. Return `Match.value` equal to the query value the engine grouped, so the walk can attach the row to its parent.

## Contract tests

`joinhound.testing.contracts.check_tabular_source` and `check_document_source` are the checks every source runs. `check_matcher` is the check for a matcher. A new implementation is not done until those checks pass against it.

Run the project checks before a pull request:

```console
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/joinhound/core src/joinhound/engine
uv run pytest
uv run lint-imports
uv run python scripts/check_licenses.py
```

Dependencies must use an allowed license and a pinned version. Allowed licenses are Apache-2.0, MIT, BSD, ISC, PostgreSQL, PSF, and LGPL used only as an unmodified library.
