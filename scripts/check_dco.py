# SPDX-License-Identifier: Apache-2.0

"""Reject commits that do not contain a Developer Certificate of Origin sign-off."""

from __future__ import annotations

import os
import subprocess
import sys


def commit_range() -> str:
    """Return the commits introduced by this pull request or push."""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "pull_request":
        base = os.environ["GITHUB_BASE_REF"]
        # GitHub checks out a temporary merge commit. Inspect the pull request head
        # so that merge commit is not required to carry a sign-off.
        head = os.environ.get("PR_HEAD_SHA") or "HEAD"
        return f"origin/{base}..{head}"
    before = os.environ.get("GITHUB_EVENT_BEFORE", "")
    if before and set(before) != {"0"}:
        return f"{before}..HEAD"
    return "origin/main..HEAD"


def missing_signoffs(revision_range: str) -> list[str]:
    """Return commit ids in the range whose message has no Signed-off-by line."""
    completed = subprocess.run(
        ["git", "log", "--format=%H%x1f%B%x1e", revision_range],
        check=True,
        capture_output=True,
        text=True,
    )
    missing: list[str] = []
    for record in completed.stdout.split("\x1e"):
        if not record.strip():
            continue
        commit, _, message = record.strip().partition("\x1f")
        if not any(line.startswith("Signed-off-by: ") for line in message.splitlines()):
            missing.append(commit)
    return missing


def main() -> int:
    """Fail when a commit in the current range is missing its sign-off."""
    missing = missing_signoffs(commit_range())
    if not missing:
        return 0
    for commit in missing:
        print(f"Missing Signed-off-by: {commit}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
