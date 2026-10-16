# SPDX-License-Identifier: Apache-2.0

"""Run the stage 1 agents and write docs/eval/stage1.md.

The joinhound agent calls the MCP tools. The baseline agent lists the schema and
runs one read-only SELECT at a time. Neither path writes to the source database.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from mcp import Client

from joinhound.cli import _declared_drafts
from joinhound.connectors.postgres import PostgresSource
from joinhound.core.config import EngineConfig, PostgresSourceConfig
from joinhound.engine.baseline import (
    answer_confirmed,
    answer_recall,
    cited_keys,
    tables_in_sql,
    uris_from_rows,
)
from joinhound.engine.evaluate import record_key
from joinhound.engine.questions import GoldQuestion, QuestionReport, load_questions, score_questions
from joinhound.matchers import DeclaredFkMatcher
from joinhound.server import Runtime, create_server

_ROOT = Path(__file__).resolve().parents[1]
_QUESTIONS = _ROOT / "tests" / "eval" / "gold" / "pagila_questions.json"
_REPORT = _ROOT / "docs" / "eval" / "stage1.md"
_DSN = "postgresql://postgres:postgres@127.0.0.1:55433/pagila"
_ROUNDS = 4
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|copy|truncate|comment)\b",
    re.IGNORECASE,
)

_JOINHOUND_SYSTEM = (
    "Answer one question about Pagila using only tool results. "
    "Call get_context first. If truncated is true, call expand with node uris, not node ids. "
    'Cite every supporting row as pg://pagila/public.<table>#pk={"column":value}. '
    "Do not invent ids. Do not run SQL."
)
_SQL_SYSTEM = (
    "Answer one question about Pagila. list_schema describes the tables. "
    "query runs one read-only SELECT and returns at most 30 rows. "
    "Select the primary key columns. "
    'Cite every supporting row as pg://pagila/public.<table>#pk={"column":value}. '
    "Do not invent ids."
)
_JOINHOUND_TOOLS = [
    {
        "name": "get_context",
        "description": "Return a bounded graph of records related to the question.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "budget_tokens": {"type": "integer"},
                "max_depth": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "expand",
        "description": "Add neighbors of records already returned. Pass node uris.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_uris": {"type": "array", "items": {"type": "string"}},
                "depth": {"type": "integer"},
                "budget_tokens": {"type": "integer"},
            },
            "required": ["node_uris"],
        },
    },
    {
        "name": "get_record",
        "description": "Read one full row by its source uri.",
        "input_schema": {
            "type": "object",
            "properties": {"uri": {"type": "string"}},
            "required": ["uri"],
        },
    },
]
_SQL_TOOLS = [
    {
        "name": "list_schema",
        "description": "List public tables, columns, and primary keys.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "query",
        "description": "Run one read-only SELECT. At most 30 rows are returned.",
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
]


@dataclass(frozen=True)
class AgentScore:
    recall: float
    confirmed: bool
    note: str


def main() -> None:
    env = _env()
    questions = load_questions(_QUESTIONS)
    if len(sys.argv) > 1:
        questions = questions[: int(sys.argv[1])]
    source = PostgresSource(
        "pagila",
        PostgresSourceConfig(
            type="postgres",
            dsn=_DSN,
            schemas=["public"],
            statement_timeout_ms=30_000,
        ),
    )
    with source:
        links = _declared_drafts(source)
        context = score_questions(
            questions,
            source,
            links,
            {"declared_fk": DeclaredFkMatcher(source)},
        )
        print(
            f"get_context recall {context.recall:.3f} precision {context.precision:.3f}",
            flush=True,
        )
        server = create_server(
            Runtime(engine=EngineConfig(), sources=[("pagila", source)], links=links)
        )
        joinhound = asyncio.run(_joinhound_scores(server, questions, env))
        sql = _sql_scores(_DSN, questions, env)
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(
        _render(env["JUDGE_MODEL"], context, questions, joinhound, sql),
        encoding="utf-8",
    )
    print(f"wrote {_REPORT}", flush=True)


async def _joinhound_scores(
    server: object,
    questions: list[GoldQuestion],
    env: dict[str, str],
) -> list[AgentScore]:
    scores: list[AgentScore] = []
    async with Client(server) as client:
        for question in questions:
            scores.append(await _one_joinhound(client, question, env))
            print(f"joinhound {question.id} recall {scores[-1].recall:.3f}", flush=True)
            if scores[-1].note.startswith("HTTP "):
                break
    return scores


async def _one_joinhound(client: Client, question: GoldQuestion, env: dict[str, str]) -> AgentScore:
    observed: set[tuple[str, str, str]] = set()

    async def dispatch(name: str, arguments: object) -> str:
        if not isinstance(arguments, dict):
            return "Tool arguments must be an object"
        try:
            result = await client.call_tool(name, arguments)
        except Exception as exc:
            return f"Tool failed: {exc}"
        payload = result.structured_content
        text = json.dumps(payload if payload is not None else str(result.content), default=str)
        observed.update(cited_keys(text))
        return _clip(text)

    try:
        answer = await _converse(env, _JOINHOUND_SYSTEM, _JOINHOUND_TOOLS, question.query, dispatch)
    except ApiError as exc:
        return AgentScore(0.0, False, str(exc))
    return AgentScore(answer_recall(answer, question.uris), answer_confirmed(answer, observed), "")


def _sql_scores(dsn: str, questions: list[GoldQuestion], env: dict[str, str]) -> list[AgentScore]:
    scores: list[AgentScore] = []
    with psycopg.connect(dsn) as connection:
        connection.execute("SET default_transaction_read_only = on")
        connection.execute("SET statement_timeout = '5s'")
        keys = _primary_keys(connection)
        schema = _schema_text(connection, keys)
        for question in questions:
            scores.append(_one_sql(connection, keys, schema, question, env))
            print(f"sql {question.id} recall {scores[-1].recall:.3f}", flush=True)
            if scores[-1].note.startswith("HTTP "):
                break
    return scores


def _one_sql(
    connection: psycopg.Connection[tuple[object, ...]],
    keys: dict[str, list[str]],
    schema: str,
    question: GoldQuestion,
    env: dict[str, str],
) -> AgentScore:
    observed: set[tuple[str, str, str]] = set()

    def dispatch(name: str, arguments: object) -> str:
        if name == "list_schema":
            return schema
        if name != "query" or not isinstance(arguments, dict):
            return "Unknown tool"
        sql = arguments.get("sql")
        if not isinstance(sql, str):
            return "query needs a sql string"
        rejected = _reject_sql(sql)
        if rejected is not None:
            return rejected
        try:
            cursor = connection.execute(sql)
            rows = cursor.fetchmany(30)
        except psycopg.Error as exc:
            connection.rollback()
            return f"Query failed: {exc.__class__.__name__}"
        description = cursor.description or []
        named = []
        for row in rows:
            named.append(
                {column.name: value for column, value in zip(description, row, strict=False)}
            )
        uris = uris_from_rows(named, keys, tables_in_sql(sql))
        observed.update(record_key(uri) for uri in uris)
        body = json.dumps({"rows": named, "uris": uris}, default=str)
        return _clip(body)

    try:
        answer = asyncio.run(
            _converse(env, _SQL_SYSTEM, _SQL_TOOLS, question.query, _sync_dispatch(dispatch))
        )
    except ApiError as exc:
        return AgentScore(0.0, False, str(exc))
    return AgentScore(answer_recall(answer, question.uris), answer_confirmed(answer, observed), "")


def _sync_dispatch(dispatch: object):
    async def wrapped(name: str, arguments: object) -> str:
        return dispatch(name, arguments)  # type: ignore[operator]

    return wrapped


async def _converse(
    env: dict[str, str],
    system: str,
    tools: list[dict[str, object]],
    question: str,
    dispatch: object,
) -> str:
    messages: list[dict[str, object]] = [{"role": "user", "content": question}]
    final = ""
    for _ in range(_ROUNDS):
        reply = _messages(env, system, tools, messages)
        content = reply.get("content")
        if not isinstance(content, list):
            break
        messages.append({"role": "assistant", "content": content})
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        final = "".join(str(text) for text in texts)
        uses = [
            block
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        if not uses:
            return final
        results = []
        for block in uses:
            text = await dispatch(str(block.get("name", "")), block.get("input", {}))  # type: ignore[operator]
            results.append({"type": "tool_result", "tool_use_id": block.get("id"), "content": text})
        messages.append({"role": "user", "content": results})
    return final


def _messages(
    env: dict[str, str],
    system: str,
    tools: list[dict[str, object]],
    messages: list[dict[str, object]],
) -> dict[str, object]:
    base = env["LLM_BASE_URL"].rstrip("/")
    url = base if base.endswith("/messages") else f"{base}/messages"
    payload = json.dumps(
        {
            "model": env["JUDGE_MODEL"],
            "max_tokens": 800,
            "system": system,
            "tools": tools,
            "messages": messages,
        }
    ).encode()
    completed = subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--max-time",
            "90",
            "--output",
            "-",
            "--write-out",
            "\n%{http_code}",
            "-X",
            "POST",
            url,
            "-H",
            "content-type: application/json",
            "-H",
            f"x-api-key: {env['LLM_API_KEY']}",
            "-H",
            f"anthropic-workspace-id: {env['ANTHROPIC_WORKSPACE_ID']}",
            "-H",
            "anthropic-version: 2023-06-01",
            "--data-binary",
            "@-",
        ],
        input=payload,
        capture_output=True,
        check=False,
    )
    raw = completed.stdout.decode(errors="replace")
    body, _, status_text = raw.rpartition("\n")
    try:
        status = int(status_text)
    except ValueError:
        detail = completed.stderr.decode(errors="replace")[:300]
        raise ApiError(0, detail or "curl produced no status") from None
    if status >= 400 or completed.returncode != 0:
        raise ApiError(status, body[:300])
    loaded = json.loads(body)
    if not isinstance(loaded, dict):
        raise ApiError(200, "Response was not an object")
    return loaded


def _reject_sql(sql: str) -> str | None:
    stripped = sql.strip().rstrip(";")
    if ";" in stripped or not stripped.lower().startswith(("select", "with")):
        return "Only a single SELECT is allowed"
    if _FORBIDDEN.search(stripped):
        return "Only a single SELECT is allowed"
    return None


def _primary_keys(connection: psycopg.Connection[tuple[object, ...]]) -> dict[str, list[str]]:
    rows = connection.execute(
        """
        SELECT kcu.table_name, kcu.column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
        ORDER BY kcu.table_name, kcu.ordinal_position
        """
    ).fetchall()
    keys: dict[str, list[str]] = {}
    for table, column in rows:
        keys.setdefault(str(table), []).append(str(column))
    return keys


def _schema_text(
    connection: psycopg.Connection[tuple[object, ...]],
    keys: dict[str, list[str]],
) -> str:
    rows = connection.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """
    ).fetchall()
    grouped: dict[str, list[str]] = {}
    for table, column, data_type in rows:
        grouped.setdefault(str(table), []).append(f"{column} {data_type}")
    lines = []
    for table, columns in grouped.items():
        pk = ", ".join(keys.get(table, []))
        lines.append(f"{table}({', '.join(columns)}) pk=({pk})")
    return "\n".join(lines)


def _render(
    model: str,
    context: QuestionReport,
    questions: list[GoldQuestion],
    joinhound: list[AgentScore],
    sql: list[AgentScore],
) -> str:
    jh_recall = _mean([item.recall for item in joinhound])
    sql_recall = _mean([item.recall for item in sql])
    jh_confirmed = _rate([item.confirmed for item in joinhound])
    sql_confirmed = _rate([item.confirmed for item in sql])
    lines = [
        "# Stage 1 baseline",
        "",
        "Twenty Pagila questions, gold rows in `tests/eval/gold/pagila_questions.json`. "
        "The source is the pinned Pagila revision `ce6e114236bb828e5ec0dc835f65f1bf1b9179f5`. "
        f"Both agents used `{model}`.",
        "",
        "## get_context",
        "",
        "Declared foreign keys, engine defaults, one call per question. "
        "Precision and recall are macro-averages. The source name in a URI is ignored.",
        "",
        f"- recall@budget: {context.recall:.3f}",
        f"- precision: {context.precision:.3f}",
        f"- latency p50: {context.latency_ms(50)} ms",
        f"- latency p95: {context.latency_ms(95)} ms",
        "",
        "The MVP targets are recall at least 0.8, precision at least 0.6, "
        "and p95 under 2 seconds. Precision is low because a hub such as language "
        "pulls in rows the question did not ask for.",
        "",
        "| Question | Recall | Precision | ms |",
        "| --- | ---: | ---: | ---: |",
    ]
    for score in context.scores:
        lines.append(f"| {score.id} | {score.recall:.3f} | {score.precision:.3f} | {score.ms} |")
    lines.extend(
        [
            "",
            "## Agents",
            "",
            "An answer is confirmed when it cites at least one row a tool returned. "
            "Answer recall is the share of gold rows cited in the final text. "
            "The MVP target for confirmed answers is 0.95. "
            "The three filmography questions score 0 because neither agent "
            "cited the full film list.",
            "",
            "| Agent | Answer recall | Confirmed answers |",
            "| --- | ---: | ---: |",
            f"| joinhound MCP | {jh_recall:.3f} | {jh_confirmed:.3f} |",
            f"| schema + SELECT | {sql_recall:.3f} | {sql_confirmed:.3f} |",
            "",
            f"Recall gap (joinhound minus SQL): {jh_recall - sql_recall:+.3f}. "
            f"Confirmed-answer gap: {jh_confirmed - sql_confirmed:+.3f}.",
            "",
            _gap_text(jh_recall, sql_recall, jh_confirmed, sql_confirmed),
            "",
            "| Question | joinhound recall | joinhound confirmed | SQL recall | SQL confirmed |",
            "| --- | ---: | --- | ---: | --- |",
        ]
    )
    for index, question in enumerate(questions):
        left = joinhound[index] if index < len(joinhound) else AgentScore(0.0, False, "not run")
        right = sql[index] if index < len(sql) else AgentScore(0.0, False, "not run")
        cells = [
            question.id,
            f"{left.recall:.3f}",
            _yes(left),
            f"{right.recall:.3f}",
            _yes(right),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def _gap_text(
    jh_recall: float,
    sql_recall: float,
    jh_confirmed: float,
    sql_confirmed: float,
) -> str:
    recall_points = (jh_recall - sql_recall) * 100
    confirmed_points = (jh_confirmed - sql_confirmed) * 100
    if recall_points >= 10 and confirmed_points >= 10:
        return (
            "Both gaps are at least 10 percentage points. "
            "The specification keeps fuzzy matching as the next stage."
        )
    return (
        "The gaps are not both at least 10 percentage points in joinhound's favor. "
        "The specification then moves documents ahead of fuzzy matching."
    )


def _yes(score: AgentScore) -> str:
    if score.note:
        return score.note.replace("|", "/")
    return "yes" if score.confirmed else "no"


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _rate(values: list[bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def _env() -> dict[str, str]:
    values = dict(os.environ)
    env_path = _ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key, value)
    required = ("LLM_API_KEY", "LLM_BASE_URL", "JUDGE_MODEL", "ANTHROPIC_WORKSPACE_ID")
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise SystemExit(f"Missing environment values: {', '.join(missing)}")
    return values


class ApiError(RuntimeError):
    """The model endpoint rejected a request."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")


def _clip(text: str) -> str:
    if len(text) > 16_000:
        return text[:16_000] + "\n[truncated]"
    return text


if __name__ == "__main__":
    main()
