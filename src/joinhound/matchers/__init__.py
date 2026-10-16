# SPDX-License-Identifier: Apache-2.0

"""Relationship matchers."""

from joinhound.matchers.declared import DeclaredFkMatcher
from joinhound.matchers.documents import DocumentMatcher
from joinhound.matchers.exact import ExactMatcher
from joinhound.matchers.fuzzy import FuzzyMatcher
from joinhound.matchers.normalized import NormalizedMatcher

__all__ = [
    "DeclaredFkMatcher",
    "DocumentMatcher",
    "ExactMatcher",
    "FuzzyMatcher",
    "NormalizedMatcher",
]
