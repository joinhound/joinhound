# SPDX-License-Identifier: Apache-2.0

"""Tests for column fingerprints."""

from joinhound.core.models import ColumnProfile
from joinhound.profiler.fingerprint import minhash_bytes, profile_columns, value_pattern
from joinhound.testing.memory import MemoryTabularSource


def test_value_pattern_collapses_letters_and_digits() -> None:
    assert value_pattern("PRD-901") == "A-9"
    assert value_pattern("Academy Dinosaur") == "A A"


def test_minhash_is_stable_and_fixed_width() -> None:
    first = minhash_bytes(["English", " english "])
    second = minhash_bytes(["English", " english "])

    assert first == second
    assert len(first) == 512


def test_profile_uses_the_dominant_pattern() -> None:
    source = MemoryTabularSource(
        {
            "products": [
                {"id": 1, "sku": "PRD-901"},
                {"id": 2, "sku": "AB-12"},
            ]
        }
    )

    profiles = {item.column_name: item for item in profile_columns(source)}
    sku = profiles["sku"]

    assert isinstance(sku, ColumnProfile)
    assert sku.pattern == "A-9"
    assert sku.minhash is not None
    assert len(sku.minhash) == 512
