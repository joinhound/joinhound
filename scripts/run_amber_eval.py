# SPDX-License-Identifier: Apache-2.0

"""Compare direct SQL plus dossier search with joinhound on AmbER entities."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import psycopg
from openai import OpenAI
from psycopg.rows import dict_row

from joinhound.amber_eval import (
    DOCUMENT_COLLECTION,
    AmberQuestion,
    load_questions,
)
from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import EngineConfig, PostgresSourceConfig
from joinhound.core.models import IndexedPassage, LinkDraft
from joinhound.core.protocols import LinkMatcher
from joinhound.core.uri import S3Uri, build_uri
from joinhound.engine.context import expand, get_context, read_record
from joinhound.engine.dictionary import ValueDictionary, build_dictionary
from joinhound.engine.evaluate import overlap_scores
from joinhound.engine.passages import lexical_rank
from joinhound.eval_agent import AgentResult, run_agent
from joinhound.matchers import ExactMatcher
from joinhound.matchers.documents import DocumentMatcher, Passage
from joinhound.profiler.profile import link_id

Arm = Literal["baseline", "joinhound"]

_READ_ONLY = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(ALTER|COPY|CREATE|DELETE|DROP|GRANT|INSERT|REVOKE|TRUNCATE|UPDATE)\b",
    re.IGNORECASE,
)
_SUBMIT_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": "Submit the verified final answer as short strings.",
        "parameters": {
            "type": "object",
            "properties": {"answers": {"type": "array", "items": {"type": "string"}}},
            "required": ["answers"],
            "additionalProperties": False,
        },
    },
}
_BASELINE_TOOLS: list[dict[str, object]] = [
    {
        "type": "function",
        "function": {
            "name": "describe_schema",
            "description": "Describe the relational tables. There are no declared foreign keys.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search all ambiguous-entity dossiers and return matching text and URI.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "Run one read-only PostgreSQL SELECT. At most 50 rows are returned.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    _SUBMIT_TOOL,
]
_GET_CONTEXT_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "get_context",
        "description": (
            "Resolve the dossier named in the question and return the requested "
            "property value, the subject it belongs to, and provenance. Call this first."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
_JOINHOUND_TOOLS: list[dict[str, object]] = [
    _GET_CONTEXT_TOOL,
    *_BASELINE_TOOLS[:-1],
    {
        "type": "function",
        "function": {
            "name": "expand",
            "description": "Follow more approved links from returned node URIs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_uris": {"type": "array", "items": {"type": "string"}},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 3},
                },
                "required": ["node_uris"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_record",
            "description": "Read the full database row for a provenance URI.",
            "parameters": {
                "type": "object",
                "properties": {"uri": {"type": "string"}},
                "required": ["uri"],
                "additionalProperties": False,
            },
        },
    },
    _SUBMIT_TOOL,
]

_SCHEMA = """
The PostgreSQL database contains three source tables with no declared foreign keys:
- amber_entities(qid PK, ambiguous_name, is_head, popularity)
- amber_facts(id PK, qid, property_id, property_name, answer)
- amber_fact_aliases(id PK, fact_id, alias)

Names are deliberately ambiguous. A dossier omits qid and identifies its subject by
one fact alias. Infer any relationships from the column values. Do not answer with the
known clue: return the property requested by the question.
""".strip()


def main() -> None:
    """Run deterministic retrieval and/or the paired agent comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--bundle", type=Path, default=Path("cache/amber-eval/bundle"))
    parser.add_argument("--model", default=os.environ.get("JUDGE_MODEL"))
    parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL"))
    parser.add_argument("--api-key", default=os.environ.get("LLM_API_KEY"))
    parser.add_argument("--workspace-id", default=os.environ.get("ANTHROPIC_WORKSPACE_ID"))
    parser.add_argument("--mode", choices=("retrieval", "agent", "both"), default="both")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-tool-calls", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument(
        "--access",
        choices=("full", "files", "blind"),
        default="full",
        help="full keeps SQL and the join hint. files drops SQL. blind keeps SQL without the hint.",
    )
    parser.add_argument("--out", type=Path, default=Path("cache/amber-eval/results.json"))
    args = parser.parse_args()
    if args.mode in {"agent", "both"} and (not args.model or not args.api_key):
        parser.error("--model and --api-key (or JUDGE_MODEL and LLM_API_KEY) are required")

    available = [
        question
        for question in load_questions(args.bundle / "questions.json")
        if question.split == args.split
    ]
    selected = _stratified(available, args.limit, args.seed)
    passages = _passages(args.bundle / "files")
    with PostgresSource(
        "amber",
        PostgresSourceConfig(
            type="postgres",
            dsn=args.dsn,
            schemas=["public"],
            statement_timeout_ms=30_000,
        ),
    ) as source:
        links = _links()
        matchers: dict[str, LinkMatcher] = {
            "exact": ExactMatcher(source),
            "column_documents": DocumentMatcher(
                source,
                [Passage(item.collection_id, {"uri": item.uri}, item.text) for item in passages],
            ),
        }
        dictionary = build_dictionary(source, links)
        retrieval = (
            _retrieval(selected, source, links, matchers, dictionary, passages)
            if args.mode in {"retrieval", "both"}
            else None
        )
        results: dict[Arm, list[AgentResult]] | None = None
        if args.mode in {"agent", "both"}:
            headers = {"anthropic-workspace-id": args.workspace_id} if args.workspace_id else None
            client = OpenAI(api_key=args.api_key, base_url=args.base_url, default_headers=headers)
            results = {"baseline": [], "joinhound": []}
            order_random = random.Random(args.seed)
            baseline_tools, joinhound_tools = _tool_lists(args.access)
            for question in selected:
                baseline = _BaselineTools(args.dsn, passages, blind=args.access == "blind")
                joinhound = _JoinhoundTools(baseline, source, links, matchers, dictionary, passages)
                arms: list[
                    tuple[Arm, list[dict[str, object]], _BaselineTools | _JoinhoundTools]
                ] = [
                    ("baseline", baseline_tools, baseline),
                    ("joinhound", joinhound_tools, joinhound),
                ]
                order_random.shuffle(arms)
                for arm, tools, executor in arms:
                    results[arm].append(
                        run_agent(
                            client,
                            args.model,
                            question,  # type: ignore[arg-type]
                            tools,
                            executor.execute,
                            max_tool_calls=args.max_tool_calls,
                        )
                    )
                    print(
                        f"{len(results[arm])}/{len(selected)} {arm} {question.kind} "
                        f"recall={results[arm][-1].answer_recall:.2f}",
                        file=sys.stderr,
                        flush=True,
                    )

    payload = {
        "model": args.model,
        "access": args.access,
        "split": args.split,
        "questions": len(selected),
        "retrieval": retrieval,
        "agent": (
            {
                "summary": {arm: _summary(items) for arm, items in results.items()},
                "by_kind": {arm: _by_kind(items, selected) for arm, items in results.items()},
                "results": {
                    arm: [asdict(item) for item in items] for arm, items in results.items()
                },
            }
            if results is not None
            else None
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"retrieval": retrieval, "agent": payload["agent"]["summary"] if results else None},
            indent=2,
            sort_keys=True,
        )
    )


def _tool_name(tool: Mapping[str, object]) -> str:
    function = tool.get("function")
    if isinstance(function, dict):
        return str(function.get("name", ""))
    return ""


def _tool_lists(access: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return the baseline and joinhound tool lists for one access mode."""
    if access == "full":
        return _BASELINE_TOOLS, _JOINHOUND_TOOLS
    hidden = {"run_sql", "describe_schema"} if access == "files" else set()
    return (
        [tool for tool in _BASELINE_TOOLS if _tool_name(tool) not in hidden],
        [tool for tool in _JOINHOUND_TOOLS if _tool_name(tool) not in hidden],
    )


class _BaselineTools:
    def __init__(
        self,
        dsn: str,
        passages: Sequence[IndexedPassage],
        *,
        blind: bool = False,
    ) -> None:
        self._dsn = dsn
        self._passages = passages
        self._blind = blind

    def execute(self, name: str, arguments: Mapping[str, object]) -> str:
        try:
            return self._execute(name, arguments)
        except (TypeError, ValueError) as error:
            return json.dumps({"error": str(error)})

    def _execute(self, name: str, arguments: Mapping[str, object]) -> str:
        if name == "describe_schema":
            return self._columns() if self._blind else _SCHEMA
        if name == "search_files":
            query = str(arguments.get("query", ""))
            limit = min(max(int(arguments.get("limit", 5)), 1), 20)
            by_uri = {passage.uri: passage for passage in self._passages}
            return json.dumps(
                [
                    {"uri": uri, "text": by_uri[uri].text}
                    for uri in lexical_rank(query, self._passages)[:limit]
                ]
            )
        if name == "run_sql":
            return self._sql(str(arguments.get("query", "")))
        raise ValueError(f"Unknown baseline tool: {name}")

    def _columns(self) -> str:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position
                """
            ).fetchall()
        return json.dumps([dict(row) for row in rows])

    def _sql(self, query: str) -> str:
        if (
            not _READ_ONLY.match(query)
            or _FORBIDDEN.search(query)
            or ";" in query.rstrip().rstrip(";")
        ):
            return json.dumps({"error": "Only one read-only SELECT or WITH query is allowed"})
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(query).fetchmany(51)
        except psycopg.Error as error:
            message = getattr(error.diag, "message_primary", None) or "The query failed"
            return json.dumps({"error": message})
        return json.dumps({"rows": rows[:50], "truncated": len(rows) > 50}, default=str)


class _JoinhoundTools:
    def __init__(
        self,
        baseline: _BaselineTools,
        source: PostgresSource,
        links: Sequence[LinkDraft],
        matchers: Mapping[str, LinkMatcher],
        dictionary: ValueDictionary,
        passages: Sequence[IndexedPassage],
    ) -> None:
        self._baseline = baseline
        self._source = source
        self._links = links
        self._matchers = matchers
        self._dictionary = dictionary
        self._passages = passages

    def execute(self, name: str, arguments: Mapping[str, object]) -> str:
        try:
            return self._execute(name, arguments)
        except (TypeError, ValueError) as error:
            return json.dumps({"error": str(error)})

    def _execute(self, name: str, arguments: Mapping[str, object]) -> str:
        if name == "get_context":
            return get_context(
                str(arguments.get("query", "")),
                self._source,
                self._links,
                self._matchers,
                _engine(4),
                dictionary=self._dictionary,
                passages=self._passages,
            ).model_dump_json()
        if name == "expand":
            raw = arguments.get("node_uris", [])
            uris = [str(uri) for uri in raw] if isinstance(raw, list) else []
            depth = min(max(int(arguments.get("depth", 1)), 1), 3)
            return expand(
                uris,
                self._source,
                self._links,
                self._matchers,
                _engine(depth),
                depth=depth,
                budget_tokens=2_000,
            ).model_dump_json()
        if name == "get_record":
            try:
                return read_record(str(arguments.get("uri", "")), self._source).model_dump_json()
            except ValueError as error:
                return json.dumps({"error": str(error)})
        return self._baseline.execute(name, arguments)


def _passages(root: Path) -> list[IndexedPassage]:
    passages = [
        IndexedPassage(
            uri=build_uri(S3Uri(source="amber-dossiers", key=path.name)),
            collection_id=DOCUMENT_COLLECTION,
            text=path.read_text(encoding="utf-8"),
            page=1,
            bbox=(0.0, 0.0, 1.0, 1.0),
        )
        for path in sorted(root.glob("dossier-*.txt"))
    ]
    if not passages:
        raise ValueError(f"No dossier files found in {root}")
    return passages


def _links() -> list[LinkDraft]:
    entities = "pg://amber/public.amber_entities"
    facts = "pg://amber/public.amber_facts"
    aliases = "pg://amber/public.amber_fact_aliases"
    return [
        LinkDraft(
            link_id=link_id(facts, "qid", entities, "qid"),
            src_collection=facts,
            src_column="qid",
            dst_collection=entities,
            dst_column="qid",
            match_type="exact",
            origin="eval",
            confidence=1.0,
            status="approved",
            cardinality="N:1",
        ),
        LinkDraft(
            link_id=link_id(aliases, "fact_id", facts, "id"),
            src_collection=aliases,
            src_column="fact_id",
            dst_collection=facts,
            dst_column="id",
            match_type="exact",
            origin="eval",
            confidence=1.0,
            status="approved",
            cardinality="N:1",
        ),
        LinkDraft(
            link_id="amber_fact_aliases.alias__dossiers",
            src_collection=aliases,
            src_column="alias",
            dst_collection=DOCUMENT_COLLECTION,
            match_type="column_documents",
            origin="eval",
            confidence=1.0,
            status="approved",
        ),
        LinkDraft(
            link_id="amber_entities.ambiguous_name__dossiers",
            src_collection=entities,
            src_column="ambiguous_name",
            dst_collection=DOCUMENT_COLLECTION,
            match_type="column_documents",
            origin="eval",
            confidence=1.0,
            status="approved",
        ),
    ]


def _engine(depth: int) -> EngineConfig:
    return EngineConfig(
        seeds_k=4,
        max_depth=depth,
        beam_width=24,
        fanout=12,
        child_fanout=12,
        max_paths=8,
        budget_tokens=2_000,
        timeout_ms=30_000,
    )


def _retrieval(
    questions: Sequence[AmberQuestion],
    source: PostgresSource,
    links: Sequence[LinkDraft],
    matchers: Mapping[str, LinkMatcher],
    dictionary: ValueDictionary,
    passages: Sequence[IndexedPassage],
) -> dict[str, object]:
    settings = {"flat": _engine(1), "joinhound": _engine(4)}
    samples: dict[str, list[dict[str, float]]] = {arm: [] for arm in settings}
    by_kind: dict[str, dict[str, list[dict[str, float]]]] = {arm: {} for arm in settings}
    for question in questions:
        for arm, config in settings.items():
            response = get_context(
                question.query,
                source,
                links,
                matchers,
                config,
                dictionary=dictionary,
                passages=passages,
            )
            precision, recall = overlap_scores(
                [node.uri for node in response.nodes], question.evidence
            )
            item = {
                "precision": precision,
                "recall": recall,
                "latency_ms": float(response.stats.ms),
            }
            samples[arm].append(item)
            by_kind[arm].setdefault(question.kind, []).append(item)
    return {
        arm: {
            "overall": _retrieval_summary(items),
            "by_kind": {
                kind: _retrieval_summary(kind_items)
                for kind, kind_items in sorted(by_kind[arm].items())
            },
        }
        for arm, items in samples.items()
    }


def _retrieval_summary(items: Sequence[Mapping[str, float]]) -> dict[str, float]:
    count = len(items)
    return {
        "precision": sum(item["precision"] for item in items) / count,
        "recall": sum(item["recall"] for item in items) / count,
        "mean_latency_ms": sum(item["latency_ms"] for item in items) / count,
    }


def _summary(items: Sequence[AgentResult]) -> dict[str, float]:
    count = len(items)
    return {
        "answer_recall": sum(item.answer_recall for item in items) / count,
        "confirmed_answers": sum(item.confirmed for item in items) / count,
        "mean_tool_calls": sum(item.tool_calls for item in items) / count,
        "mean_latency_ms": sum(item.latency_ms for item in items) / count,
        "prompt_tokens": float(sum(item.prompt_tokens for item in items)),
        "completion_tokens": float(sum(item.completion_tokens for item in items)),
    }


def _by_kind(
    items: Sequence[AgentResult], questions: Sequence[AmberQuestion]
) -> dict[str, dict[str, float]]:
    kinds = {question.id: question.kind for question in questions}
    grouped: dict[str, list[AgentResult]] = {}
    for item in items:
        grouped.setdefault(kinds[item.question_id], []).append(item)
    return {kind: _summary(group) for kind, group in sorted(grouped.items())}


def _stratified(questions: Sequence[AmberQuestion], limit: int, seed: int) -> list[AmberQuestion]:
    kinds = list(dict.fromkeys(question.kind for question in questions))
    if not kinds or limit <= 0 or limit % len(kinds):
        raise ValueError(f"--limit must be a positive multiple of {len(kinds) or 2}")
    each = limit // len(kinds)
    rng = random.Random(seed)
    selected: list[AmberQuestion] = []
    for kind in kinds:
        group = [question for question in questions if question.kind == kind]
        rng.shuffle(group)
        if len(group) < each:
            raise ValueError(f"Not enough {kind} questions for --limit {limit}")
        selected.extend(group[:each])
    rng.shuffle(selected)
    return selected


if __name__ == "__main__":
    main()
