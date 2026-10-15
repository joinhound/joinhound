# SPDX-License-Identifier: Apache-2.0

"""Load implementations registered through joinhound entry-point groups."""

from importlib.metadata import entry_points


def load_plugins(group: str) -> dict[str, object]:
    """Return the registered implementations for one entry-point group, by name."""
    return {entry.name: entry.load() for entry in entry_points(group=group)}
