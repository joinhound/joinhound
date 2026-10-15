# SPDX-License-Identifier: Apache-2.0

"""Tests for the dependency license allow list."""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "check_licenses.py"
_spec = importlib.util.spec_from_file_location("check_licenses", _SCRIPT)
assert _spec is not None
assert _spec.loader is not None
check_licenses = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_licenses)


def test_allowed_licenses() -> None:
    assert check_licenses.license_allowed("typer", "MIT")
    assert check_licenses.license_allowed("packaging", "Apache-2.0 OR BSD-2-Clause")
    assert check_licenses.license_allowed("psycopg", "LGPL-3.0-only")
    assert check_licenses.license_allowed("yoyo-migrations", "Apache Software License")


def test_pathspec_mpl_exception_is_specific() -> None:
    assert check_licenses.license_allowed("pathspec", "Mozilla Public License 2.0 (MPL 2.0)")
    assert check_licenses.license_allowed("certifi", "Mozilla Public License 2.0 (MPL 2.0)")
    numpy = "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"
    assert check_licenses.license_allowed("numpy", numpy)
    assert not check_licenses.license_allowed("another", "Mozilla Public License 2.0 (MPL 2.0)")
    assert not check_licenses.license_allowed("another", numpy)


def test_gpl_is_rejected() -> None:
    assert not check_licenses.license_allowed("example", "GPL-3.0-only")
