# SPDX-License-Identifier: Apache-2.0

"""Sources and approved links used by one server process."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import AppConfig, EngineConfig, PostgresSourceConfig
from joinhound.core.models import LinkDraft
from joinhound.core.protocols import TabularSource
from joinhound.index.model import model_links


@dataclass
class Runtime:
    """What a tool call can read. Injected sources are not opened or closed here."""

    engine: EngineConfig
    sources: list[tuple[str, TabularSource]] | None = None
    links: list[LinkDraft] | None = None
    settings: AppConfig | None = None

    @contextmanager
    def session(self) -> Iterator[tuple[list[tuple[str, TabularSource]], list[LinkDraft]]]:
        """Yield sources and links, closing connections this runtime opened."""
        if self.sources is not None:
            yield self.sources, list(self.links or [])
            return
        if self.settings is None:
            yield [], []
            return
        opened: list[tuple[str, PostgresSource]] = []
        try:
            for name, source_config in self.settings.sources.items():
                if not isinstance(source_config, PostgresSourceConfig):
                    continue
                opened.append((name, PostgresSource(name, source_config)))
            yield (
                [(name, source) for name, source in opened],
                model_links(self.settings.kg_database),
            )
        finally:
            for _name, source in opened:
                source.close()


def runtime_from_config(settings: AppConfig) -> Runtime:
    """Bind a server to a configuration file. Connections open on the first tool call."""
    return Runtime(engine=settings.engine, settings=settings)
