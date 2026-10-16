# SPDX-License-Identifier: Apache-2.0

"""Tests for entry-point discovery."""

from joinhound.connectors.postgres import PostgresSource
from joinhound.core.registry import load_plugins
from joinhound.formats import OssieFormat
from joinhound.llm.none import NoneJudge
from joinhound.llm.openai_judge import OpenAIJudge
from joinhound.matchers import DeclaredFkMatcher, ExactMatcher, FuzzyMatcher, NormalizedMatcher


def test_registry_finds_builtin_judge() -> None:
    plugins = load_plugins("joinhound.judges")

    assert plugins["none"] is NoneJudge
    assert plugins["openai"] is OpenAIJudge


def test_registry_finds_postgres_connector() -> None:
    plugins = load_plugins("joinhound.connectors")

    assert plugins["postgres"] is PostgresSource


def test_registry_finds_matchers() -> None:
    plugins = load_plugins("joinhound.matchers")

    assert plugins["declared_fk"] is DeclaredFkMatcher
    assert plugins["exact"] is ExactMatcher
    assert plugins["normalized"] is NormalizedMatcher
    assert plugins["fuzzy"] is FuzzyMatcher


def test_registry_finds_ossie_format() -> None:
    plugins = load_plugins("joinhound.model_formats")

    assert plugins["ossie"] is OssieFormat


def test_unknown_group_is_empty() -> None:
    assert load_plugins("joinhound.missing") == {}
