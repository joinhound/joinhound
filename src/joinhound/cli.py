# SPDX-License-Identifier: Apache-2.0

"""Command-line entry point for the pre-alpha package."""

import argparse

from joinhound import __version__


def main() -> None:
    """Run the Joinhound command-line interface."""
    parser = argparse.ArgumentParser(
        prog="joinhound",
        description="Joinhound is currently pre-alpha.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.parse_args()
