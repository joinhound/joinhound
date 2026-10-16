# SPDX-License-Identifier: Apache-2.0

"""OpenAI-compatible relationship judge."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import psycopg
from psycopg.types.json import Json

from joinhound.core.models import Candidate, JudgeVerdict
from joinhound.profiler.fingerprint import value_pattern

_PROMPTS = Path(__file__).parent / "prompts"
_SYSTEM = (_PROMPTS / "judge_system.txt").read_text(encoding="utf-8")
_USER = (_PROMPTS / "judge_user.txt").read_text(encoding="utf-8")
_VALUE_KEYS = frozenset({"matches", "misses"})


class OpenAIJudge:
    """Ask an OpenAI-compatible chat model. Identical prompts reuse a cached verdict."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        redact: bool = False,
        sensitive_columns: list[str] | None = None,
        dsn: str | None = None,
        client: object | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model or "gpt-4o-mini"
        self._redact = redact
        self._sensitive = set(sensitive_columns or [])
        self._dsn = dsn
        self._client = client
        self._memory: dict[str, JudgeVerdict] = {}

    def review(self, candidate: Candidate) -> JudgeVerdict:
        """Return the structured decision for one candidate."""
        prompt = _prompt(candidate, redact=self._redact, sensitive=self._sensitive)
        key = hashlib.sha256(prompt.encode()).hexdigest()
        cached = self._memory.get(key)
        if cached is None:
            cached = _read_cache(self._dsn, key)
        if cached is not None:
            self._memory[key] = cached
            return cached
        verdict = JudgeVerdict.model_validate_json(self._complete(prompt))
        self._memory[key] = verdict
        _write_cache(self._dsn, key, verdict)
        return verdict

    def _complete(self, prompt: str) -> str:
        client = self._client
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=self._base_url, api_key=self._api_key or "missing")
            self._client = client
        from joinhound.telemetry import span

        with span(
            "gen_ai.chat",
            {
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": self._model,
                "gen_ai.system": "openai",
            },
        ):
            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content:
            raise ValueError("The judge returned an empty response")
        return content


def _prompt(candidate: Candidate, *, redact: bool, sensitive: set[str]) -> str:
    evidence = dict(candidate.evidence)
    column_names = {
        str(evidence.get("src_column", "")),
        str(evidence.get("dst_column", "")),
        str(evidence.get("column", "")),
    }
    if redact and column_names & sensitive:
        evidence = _redacted(evidence)
    rendered = json.dumps(evidence, sort_keys=True, default=str)
    return _USER.format(
        match_type=candidate.match_type,
        confidence=candidate.confidence,
        evidence=rendered,
    )


def _redacted(evidence: dict[str, object]) -> dict[str, object]:
    hidden: dict[str, object] = {}
    for key, value in evidence.items():
        if key in _VALUE_KEYS and isinstance(value, list):
            hidden[key] = [value_pattern(str(item)) for item in value]
        else:
            hidden[key] = value
    return hidden


def _read_cache(dsn: str | None, key: str) -> JudgeVerdict | None:
    if dsn is None:
        return None
    with psycopg.connect(dsn) as connection:
        present = connection.execute("SELECT to_regclass('kg.judge_cache')").fetchone()
        if present is None or present[0] is None:
            return None
        row = connection.execute(
            "SELECT verdict::text FROM kg.judge_cache WHERE cache_key = %s",
            (key,),
        ).fetchone()
    if row is None:
        return None
    return JudgeVerdict.model_validate_json(str(row[0]))


def _write_cache(dsn: str | None, key: str, verdict: JudgeVerdict) -> None:
    if dsn is None:
        return
    with psycopg.connect(dsn) as connection:
        present = connection.execute("SELECT to_regclass('kg.judge_cache')").fetchone()
        if present is None or present[0] is None:
            return
        connection.execute(
            """
            INSERT INTO kg.judge_cache (cache_key, verdict)
            VALUES (%s, %s)
            ON CONFLICT (cache_key) DO NOTHING
            """,
            (key, Json(verdict.model_dump())),
        )
        connection.commit()
