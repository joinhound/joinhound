# SPDX-License-Identifier: Apache-2.0

"""Check installed licenses against the project allow list."""

from __future__ import annotations

import json
import subprocess
import sys

ALLOWED = {
    "apache software license",
    "apache-2.0",
    "bsd",
    "bsd license",
    "bsd-2-clause",
    "bsd-3-clause",
    "isc",
    "isc license (iscl)",
    "lgpl-2.1-only",
    "lgpl-2.1-or-later",
    "lgpl-3.0-only",
    "lgpl-3.0-or-later",
    "mit",
    "mit license",
    "postgresql",
    "psf-2.0",
}

# Unmodified MPL-2.0 libraries pulled in by required tools.
# pathspec: mypy. certifi: testcontainers via requests.
# See docs/decisions/0001-mpl-pathspec.md and docs/decisions/0004-mpl-certifi.md.
TRANSITIVE_EXCEPTIONS = {
    ("certifi", "mozilla public license 2.0 (mpl 2.0)"),
    ("pathspec", "mozilla public license 2.0 (mpl 2.0)"),
}


def license_allowed(name: str, license_name: str) -> bool:
    """Return whether a distribution's declared license is acceptable."""
    normalized = license_name.strip().lower()
    if (name.lower(), normalized) in TRANSITIVE_EXCEPTIONS:
        return True
    parts = [part.strip() for part in normalized.split(" or ")]
    return all(part in ALLOWED for part in parts)


def installed_licenses() -> list[tuple[str, str]]:
    """Return name and license pairs reported by pip-licenses."""
    completed = subprocess.run(
        ["pip-licenses", "--format=json"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(completed.stdout)
    return [(str(row["Name"]), str(row["License"])) for row in rows]


def main() -> int:
    """Fail when any installed distribution uses a disallowed license."""
    rejected = [
        (name, license_name)
        for name, license_name in installed_licenses()
        if not license_allowed(name, license_name)
    ]
    if not rejected:
        return 0
    for name, license_name in rejected:
        print(f"Disallowed license: {name} ({license_name})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
