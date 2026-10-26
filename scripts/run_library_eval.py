# SPDX-License-Identifier: Apache-2.0

"""Compare a SQL-plus-file-search agent with a joinhound agent."""

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
from joinhound.library_eval import DOCUMENT_COLLECTION, EvalQuestion, load_questions
from joinhound.matchers import DeclaredFkMatcher
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
        "description": "Submit the verified final answer. Call this after using evidence tools.",
        "parameters": {
            "type": "object",
            "properties": {
                "answers": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
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
            "description": "Describe the relational schema and its foreign keys.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search every case-note file and return matching text and URI.",
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
_JOINHOUND_TOOLS: list[dict[str, object]] = [
    *_BASELINE_TOOLS[:-1],
    {
        "type": "function",
        "function": {
            "name": "get_context",
            "description": "Find and traverse relevant database rows and case-note passages.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "expand",
            "description": "Follow one more hop from node URIs returned by get_context.",
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
            "description": "Read the full row for one provenance URI.",
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


def main() -> None:
    """Run both agents with the same model, questions, and tool-call limit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--bundle", type=Path, default=Path("cache/library-eval/bundle"))
    parser.add_argument("--model", default=os.environ.get("JUDGE_MODEL"))
    parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL"))
    parser.add_argument("--api-key", default=os.environ.get("LLM_API_KEY"))
    parser.add_argument("--workspace-id", default=os.environ.get("ANTHROPIC_WORKSPACE_ID"))
    parser.add_argument("--mode", choices=("retrieval", "agent", "both"), default="both")
    parser.add_argument("--suite", choices=("standard", "hard"), default="standard")
    parser.add_argument("--split", choices=("dev", "test"), default="test")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-tool-calls", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--out", type=Path, default=Path("cache/library-eval/results.json"))
    args = parser.parse_args()
    if args.mode in {"agent", "both"} and (not args.model or not args.api_key):
        parser.error("--model and --api-key (or JUDGE_MODEL and LLM_API_KEY) are required")

    filename = "hard.json" if args.suite == "hard" else "questions.json"
    available = [
        question
        for question in load_questions(args.bundle / filename)
        if question.split == args.split
    ]
    selected = _stratified(available, args.limit, args.seed)
    passages = _passages(args.bundle / "files")
    with PostgresSource(
        "library",
        PostgresSourceConfig(
            type="postgres",
            dsn=args.dsn,
            schemas=["public"],
            statement_timeout_ms=30_000,
        ),
    ) as source:
        links = _links(source)
        matchers = {
            "declared_fk": DeclaredFkMatcher(source),
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
            for question in selected:
                baseline = _BaselineTools(args.dsn, passages)
                joinhound = _JoinhoundTools(
                    baseline,
                    source,
                    links,
                    matchers,
                    dictionary,
                    passages,
                )
                arms: list[
                    tuple[Arm, list[dict[str, object]], _BaselineTools | _JoinhoundTools]
                ] = [
                    ("baseline", _BASELINE_TOOLS, baseline),
                    ("joinhound", _JOINHOUND_TOOLS, joinhound),
                ]
                order_random.shuffle(arms)
                for arm, tools, executor in arms:
                    results[arm].append(
                        run_agent(
                            client,
                            args.model,
                            question,
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
        "suite": args.suite,
        "split": args.split,
        "questions": len(selected),
        "retrieval": retrieval,
        "agent": (
            {
                "summary": {arm: _summary(items) for arm, items in results.items()},
                "by_kind": {arm: _agent_by_kind(items, selected) for arm, items in results.items()},
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


class _BaselineTools:
    def __init__(self, dsn: str, passages: Sequence[IndexedPassage]) -> None:
        self._dsn = dsn
        self._passages = passages

    def execute(self, name: str, arguments: Mapping[str, object]) -> str:
        if name == "describe_schema":
            return _SCHEMA
        if name == "search_files":
            query = str(arguments.get("query", ""))
            limit = min(max(int(arguments.get("limit", 5)), 1), 20)
            by_uri = {passage.uri: passage for passage in self._passages}
            matches = lexical_rank(query, self._passages)[:limit]
            return json.dumps(
                [{"uri": uri, "text": by_uri[uri].text} for uri in matches],
                default=str,
            )
        if name == "run_sql":
            return self._sql(str(arguments.get("query", "")))
        raise ValueError(f"Unknown baseline tool: {name}")

    def _sql(self, query: str) -> str:
        if (
            not _READ_ONLY.match(query)
            or _FORBIDDEN.search(query)
            or ";" in query.rstrip().rstrip(";")
        ):
            return json.dumps({"error": "Only one read-only SELECT or WITH query is allowed"})
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            rows = connection.execute(query).fetchmany(51)
        truncated = len(rows) > 50
        return json.dumps(
            {"rows": rows[:50], "truncated": truncated},
            default=str,
        )


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
        if name == "get_context":
            result = get_context(
                str(arguments.get("query", "")),
                self._source,
                self._links,
                self._matchers,
                _engine(5),
                dictionary=self._dictionary,
                passages=self._passages,
            )
            return result.model_dump_json()
        if name == "expand":
            raw = arguments.get("node_uris", [])
            uris = [str(uri) for uri in raw] if isinstance(raw, list) else []
            depth = min(max(int(arguments.get("depth", 1)), 1), 3)
            result = expand(
                uris,
                self._source,
                self._links,
                self._matchers,
                _engine(depth),
                depth=depth,
                budget_tokens=2_000,
            )
            return result.model_dump_json()
        if name == "get_record":
            try:
                return read_record(str(arguments.get("uri", "")), self._source).model_dump_json()
            except ValueError as error:
                return json.dumps({"error": str(error)})
        return self._baseline.execute(name, arguments)


def _passages(root: Path) -> list[IndexedPassage]:
    passages: list[IndexedPassage] = []
    for path in sorted(root.glob("case-*.txt")):
        key = f"cases/{path.name}"
        passages.append(
            IndexedPassage(
                uri=build_uri(S3Uri(source="library-cases", key=key)),
                collection_id=DOCUMENT_COLLECTION,
                text=path.read_text(encoding="utf-8"),
                page=1,
                bbox=(0.0, 0.0, 1.0, 1.0),
            )
        )
    if not passages:
        raise ValueError(f"No case files found in {root}")
    return passages


def _links(source: PostgresSource) -> list[LinkDraft]:
    links: list[LinkDraft] = []
    for foreign_key in source.declared_links():
        if len(foreign_key.src_columns) != 1 or len(foreign_key.dst_columns) != 1:
            continue
        src_column = foreign_key.src_columns[0]
        dst_column = foreign_key.dst_columns[0]
        links.append(
            LinkDraft(
                link_id=link_id(
                    foreign_key.src_collection,
                    src_column,
                    foreign_key.dst_collection,
                    dst_column,
                ),
                src_collection=foreign_key.src_collection,
                src_column=src_column,
                dst_collection=foreign_key.dst_collection,
                dst_column=dst_column,
                match_type="declared_fk",
                origin="catalog_fk",
                confidence=1.0,
                status="approved",
                cardinality="N:1",
            )
        )
    links.append(
        LinkDraft(
            link_id="eval_cases.case_ref",
            src_collection="pg://library/public.eval_cases",
            src_column="case_ref",
            dst_collection=DOCUMENT_COLLECTION,
            match_type="column_documents",
            origin="eval",
            confidence=1.0,
            status="approved",
        )
    )
    return links


def _summary(items: Sequence[AgentResult]) -> dict[str, float]:
    if not items:
        return {}
    count = len(items)
    return {
        "answer_recall": sum(item.answer_recall for item in items) / count,
        "confirmed_answers": sum(item.confirmed for item in items) / count,
        "mean_tool_calls": sum(item.tool_calls for item in items) / count,
        "mean_latency_ms": sum(item.latency_ms for item in items) / count,
        "prompt_tokens": float(sum(item.prompt_tokens for item in items)),
        "completion_tokens": float(sum(item.completion_tokens for item in items)),
    }


def _agent_by_kind(
    items: Sequence[AgentResult],
    questions: Sequence[EvalQuestion],
) -> dict[str, dict[str, float]]:
    kinds = {question.id: question.kind for question in questions}
    grouped: dict[str, list[AgentResult]] = {}
    for item in items:
        grouped.setdefault(kinds[item.question_id], []).append(item)
    return {kind: _summary(group) for kind, group in sorted(grouped.items())}


def _engine(depth: int) -> EngineConfig:
    """Use the same path budget for both retrieval arms."""
    return EngineConfig(
        seeds_k=4,
        max_depth=depth,
        beam_width=20,
        fanout=8,
        child_fanout=1,
        max_paths=6,
        budget_tokens=2_000,
        timeout_ms=30_000,
    )


def _retrieval(
    questions: Sequence[EvalQuestion],
    source: PostgresSource,
    links: Sequence[LinkDraft],
    matchers: Mapping[str, LinkMatcher],
    dictionary: ValueDictionary,
    passages: Sequence[IndexedPassage],
) -> dict[str, object]:
    samples: dict[str, list[dict[str, float]]] = {"flat": [], "joinhound": []}
    settings = {
        "flat": _engine(1),
        "joinhound": _engine(5),
    }
    per_kind: dict[str, dict[str, list[dict[str, float]]]] = {arm: {} for arm in settings}
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
                [node.uri for node in response.nodes],
                question.evidence,
            )
            item = {
                "precision": precision,
                "recall": recall,
                "latency_ms": float(response.stats.ms),
            }
            samples[arm].append(item)
            per_kind[arm].setdefault(question.kind, []).append(item)
    return {
        arm: {
            "overall": _retrieval_summary(items),
            "by_kind": {
                kind: _retrieval_summary(kind_items)
                for kind, kind_items in sorted(per_kind[arm].items())
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


def _stratified(questions: Sequence[EvalQuestion], limit: int, seed: int) -> list[EvalQuestion]:
    kinds = list(dict.fromkeys(question.kind for question in questions))
    if not kinds or limit <= 0 or limit % len(kinds):
        raise ValueError(f"--limit must be a positive multiple of {len(kinds) or 5}")
    each = limit // len(kinds)
    rng = random.Random(seed)
    selected: list[EvalQuestion] = []
    for kind in kinds:
        group = [question for question in questions if question.kind == kind]
        rng.shuffle(group)
        if len(group) < each:
            raise ValueError(f"Not enough {kind} questions for --limit {limit}")
        selected.extend(group[:each])
    rng.shuffle(selected)
    return selected


_SCHEMA = """
The PostgreSQL database contains:
- eval_cases(id PK, case_ref UNIQUE, loan_id UNIQUE FK -> loans.id)
- loans(
    id PK,
    copy_id FK -> copies.id,
    membership_id FK -> memberships.id,
    staff_id FK -> staff_profiles.id
  )
- memberships(id PK, card_number UNIQUE, library_id FK -> libraries.id, user_id FK -> users.id)
- users(id PK, first_name, last_name, email, phone)
- copies(id PK, barcode UNIQUE, book_id FK -> books.id, library_id FK -> libraries.id)
- books(id PK, title, isbn UNIQUE, publisher_id FK -> publishers.id)
- publishers(id PK, name)
- libraries(id PK, name, email, phone)
- staff_profiles(id PK, user_id UNIQUE FK -> users.id, library_id)
Case-note files contain a Reference value equal to eval_cases.case_ref.
A note may also name a person who did not borrow the copy. That name is not the member,
the staff member who recorded the loan, or the answer.
""".strip()


if __name__ == "__main__":
    main()
