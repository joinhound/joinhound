# SPDX-License-Identifier: Apache-2.0

"""Embeddings from an OpenAI-compatible API."""

from __future__ import annotations


class OpenAIEmbedder:
    """Request one vector per text from `/embeddings`."""

    def __init__(
        self,
        dim: int = 1024,
        model: str = "text-embedding-3-large",
        base_url: str | None = None,
        api_key: str | None = None,
        client: object | None = None,
    ) -> None:
        self._dim = dim
        self.model = model
        self._base_url = base_url
        self._api_key = api_key
        self._client = client

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector for each text."""
        if not texts:
            return []
        client = self._client
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=self._base_url, api_key=self._api_key or "missing")
            self._client = client
        from joinhound.telemetry import span

        with span(
            "gen_ai.embeddings",
            {
                "gen_ai.operation.name": "embeddings",
                "gen_ai.request.model": self.model,
                "gen_ai.system": "openai",
            },
        ):
            response = client.embeddings.create(model=self.model, input=texts, dimensions=self._dim)
        vectors = [list(item.embedding) for item in response.data]
        if len(vectors) != len(texts):
            raise ValueError("Embedder returned a different number of vectors than texts")
        return vectors
