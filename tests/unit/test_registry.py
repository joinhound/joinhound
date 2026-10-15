# SPDX-License-Identifier: Apache-2.0

"""Tests for entry-point discovery."""

from joinhound.connectors.postgres import PostgresSource
from joinhound.core.registry import load_plugins
from joinhound.llm.none import NoneJudge
from joinhound.matchers import DeclaredFkMatcher, ExactMatcher


def test_registry_finds_builtin_judge() -> None:
    plugins = load_plugins("joinhound.judges")

    assert plugins["none"] is NoneJudge


def test_registry_finds_postgres_connector() -> None:
    plugins = load_plugins("joinhound.connectors")

    assert plugins["postgres"] is PostgresSource


def test_registry_finds_matchers() -> None:
    plugins = load_plugins("joinhound.matchers")

    assert plugins["declared_fk"] is DeclaredFkMatcher
    assert plugins["exact"] is ExactMatcher


def test_unknown_group_is_empty() -> None:
    assert load_plugins("joinhound.missing") == {}
