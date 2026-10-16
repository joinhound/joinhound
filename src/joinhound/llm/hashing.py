# SPDX-License-Identifier: Apache-2.0

"""A local embedder that hashes character trigrams. No model is downloaded."""

from __future__ import annotations

import hashlib
import math

from joinhound.index.normalize import apply


class HashEmbedder:
    """Embed text as a normalized trigram vector of the configured dimension."""

    def __init__(self, dim: int = 1024, model: str = "joinhound-hash-v1") -> None:
        self._dim = dim
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one unit vector for each text."""
        return [_vector(text, self._dim) for text in texts]


def _vector(text: str, dim: int) -> list[float]:
    values = [0.0] * dim
    folded = apply("fold", text)
    padded = f" {folded} "
    for index in range(max(len(padded) - 2, 0)):
        gram = padded[index : index + 3]
        digest = hashlib.sha256(gram.encode()).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        values[bucket] += 1.0
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]
