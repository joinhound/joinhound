# SPDX-License-Identifier: Apache-2.0

"""Tests for the internal import contracts."""

import subprocess
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_VIOLATION = _ROOT / "src" / "joinhound" / "core" / "_violation.py"


def test_import_contracts_pass() -> None:
    completed = subprocess.run(
        ["lint-imports"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_forbidden_core_import_fails() -> None:
    _VIOLATION.write_text(
        "# SPDX-License-Identifier: Apache-2.0\nimport joinhound.engine\n",
        encoding="utf-8",
    )
    try:
        completed = subprocess.run(
            ["lint-imports"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        _VIOLATION.unlink(missing_ok=True)

    assert completed.returncode != 0
    assert "Core does not depend on other components" in completed.stdout + completed.stderr
