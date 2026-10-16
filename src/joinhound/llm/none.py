# SPDX-License-Identifier: Apache-2.0

"""A judge that does not call a model."""

from joinhound.core.models import Candidate


class NoneEmbedder:
    """Write zero vectors of the configured dimension. No model is downloaded."""

    def __init__(self, dim: int = 1024) -> None:
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one zero vector for each text."""
        return [[0.0] * self._dim for _text in texts]


class NoneJudge:
    """Leave proposed relationships for a person to review."""

    def review(self, candidate: Candidate) -> None:
        """Do not decide the candidate."""
        del candidate
        return None
