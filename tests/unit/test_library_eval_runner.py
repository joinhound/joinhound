# SPDX-License-Identifier: Apache-2.0

"""The agent comparison gives joinhound additive, not replacement, tools."""

from collections.abc import Mapping
from pathlib import Path
from runpy import run_path
from typing import Any, cast

_RUNNER = run_path(str(Path(__file__).parents[2] / "scripts/run_library_eval.py"))
_BASELINE_TOOLS = cast(list[dict[str, object]], _RUNNER["_BASELINE_TOOLS"])
_JOINHOUND_TOOLS = cast(list[dict[str, object]], _RUNNER["_JOINHOUND_TOOLS"])
_JoinhoundTools = cast(type[Any], _RUNNER["_JoinhoundTools"])


def test_joinhound_arm_contains_every_baseline_tool_plus_get_context() -> None:
    baseline = _tool_names(_BASELINE_TOOLS)
    joinhound = _tool_names(_JOINHOUND_TOOLS)

    assert baseline <= joinhound
    assert joinhound - baseline == {"get_context"}


def test_joinhound_arm_forwards_shared_tools_to_baseline() -> None:
    baseline = _RecordingBaseline()
    tools = _JoinhoundTools.__new__(_JoinhoundTools)
    tools._baseline = baseline

    result = tools.execute("search_files", {"query": "rare phrase"})

    assert result == "shared result"
    assert baseline.call == ("search_files", {"query": "rare phrase"})


def _tool_names(tools: list[dict[str, object]]) -> set[str]:
    return {
        str(tool["function"]["name"]) for tool in tools if isinstance(tool.get("function"), dict)
    }


class _RecordingBaseline:
    call: tuple[str, Mapping[str, object]] | None = None

    def execute(self, name: str, arguments: Mapping[str, object]) -> str:
        self.call = (name, arguments)
        return "shared result"
