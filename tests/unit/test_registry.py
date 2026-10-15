# SPDX-License-Identifier: Apache-2.0

"""Tests for entry-point discovery."""

from joinhound.core.registry import load_plugins
from joinhound.llm.none import NoneJudge


def test_registry_finds_builtin_judge() -> None:
    plugins = load_plugins("joinhound.judges")

    assert plugins["none"] is NoneJudge


def test_unknown_group_is_empty() -> None:
    assert load_plugins("joinhound.missing") == {}
