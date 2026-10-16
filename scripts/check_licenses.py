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
    "3-clause bsd license",
    "isc",
    "isc license (iscl)",
    "lgpl-2.1-only",
    "lgpl-2.1-or-later",
    "lgpl-3.0-only",
    "lgpl-3.0-or-later",
    "cnri-python",
    "mit",
    "mit-0",
    "mit-cmu",
    "mit license",
    "postgresql",
    "psf-2.0",
    "public-domain",
}

# Unmodified libraries pulled in by required tools, outside the base allow list.
# pathspec: mypy. certifi: testcontainers via requests.
# numpy: datasketch. Its declaration is a conjunction of permissive terms.
# pypdfium2: the PDF parser named in the specification. Pillow is MIT-CMU.
# See docs/decisions/0001-mpl-pathspec.md, 0004-mpl-certifi.md, 0008-numpy-license.md,
# and 0017-pdf-parser-licenses.md.
TRANSITIVE_EXCEPTIONS = {
    ("certifi", "mozilla public license 2.0 (mpl 2.0)"),
    ("numpy", "bsd-3-clause and 0bsd and mit and zlib and cc0-1.0"),
    ("pathspec", "mozilla public license 2.0 (mpl 2.0)"),
    ("pypdfium2", "bsd-3-clause, apache-2.0, dependency licenses"),
    # openai SDK. sniffio is Apache or MIT. tqdm is MPL-2.0 and MIT.
    ("sniffio", "apache software license; mit license"),
    ("tqdm", "mpl-2.0 and mit"),
}


def license_allowed(name: str, license_name: str) -> bool:
    """Return whether a distribution's declared license is acceptable."""
    normalized = license_name.strip().lower()
    if (name.lower(), normalized) in TRANSITIVE_EXCEPTIONS:
        return True
    if normalized.startswith("mit license") and "permission is hereby granted" in normalized:
        return True
    if " or " in normalized:
        parts = [part.strip() for part in normalized.split(" or ")]
    elif " and " in normalized:
        parts = [part.strip() for part in normalized.split(" and ")]
    else:
        parts = [normalized]
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
