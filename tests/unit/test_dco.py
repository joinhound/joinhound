# SPDX-License-Identifier: Apache-2.0

"""Tests for the Developer Certificate of Origin check."""

import importlib.util
from pathlib import Path

from pytest import MonkeyPatch

_SCRIPT = Path(__file__).parents[2] / "scripts" / "check_dco.py"
_spec = importlib.util.spec_from_file_location("check_dco", _SCRIPT)
assert _spec is not None
assert _spec.loader is not None
check_dco = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_dco)


def test_pull_request_range_uses_head_commit(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    monkeypatch.setenv("PR_HEAD_SHA", "abc123")

    assert check_dco.commit_range() == "origin/main..abc123"
