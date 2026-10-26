# SPDX-License-Identifier: Apache-2.0

"""A small, provider-neutral tool loop for end-to-end evaluations."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from openai import OpenAI

from joinhound.library_eval import EvalQuestion, answer_recall

ToolExecutor = Callable[[str, Mapping[str, object]], str]
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class AgentResult:
    """One model answer and the tool evidence that preceded it."""

    question_id: str
    answers: tuple[str, ...]
    tool_calls: int
    latency_ms: int
    answer_recall: float
    confirmed: bool
    prompt_tokens: int
    completion_tokens: int


def run_agent(
    client: OpenAI,
    model: str,
    question: EvalQuestion,
    tools: Sequence[Mapping[str, object]],
    execute: ToolExecutor,
    *,
    max_tool_calls: int = 8,
) -> AgentResult:
    """Ask one model a question, executing only the tools supplied by one arm."""
    messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": (
                "Answer from tool results only. Use tools until the answer is verified. "
                "Then call submit_answer with a list of short answer strings. Do not add prose."
            ),
        },
        {"role": "user", "content": question.query},
    ]
    outputs: list[str] = []
    calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    started = time.monotonic()

    def finish(answers: tuple[str, ...]) -> AgentResult:
        elapsed = int((time.monotonic() - started) * 1000)
        return AgentResult(
            question_id=question.id,
            answers=answers,
            tool_calls=calls,
            latency_ms=elapsed,
            answer_recall=answer_recall(list(answers), question.answers),
            confirmed=_confirmed(question.answers, outputs),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    while True:
        response = client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            tools=cast(Any, list(tools)),
            tool_choice="auto",
        )
        prompt_tokens += response.usage.prompt_tokens if response.usage else 0
        completion_tokens += response.usage.completion_tokens if response.usage else 0
        message = response.choices[0].message
        messages.append(cast(dict[str, object], message.model_dump(exclude_none=True)))
        if not message.tool_calls:
            return finish(_answers(message.content))
        for call in message.tool_calls:
            if call.function.name in {"submit_answer", "json"}:
                return finish(_submitted_answers(_arguments(call.function.arguments)))
            if calls >= max_tool_calls:
                return finish(())
            arguments = _arguments(call.function.arguments)
            output = execute(call.function.name, arguments)
            outputs.append(output)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": output,
                }
            )
            calls += 1


def _answers(content: str | None) -> tuple[str, ...]:
    if not content:
        return ()
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        content = "\n".join(lines[1:-1])
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return (content.strip(),)
    raw = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return ()
    return tuple(str(value) for value in raw)


def _arguments(value: str) -> dict[str, object]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("Tool arguments must be JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("Tool arguments must be an object")
    return {str(key): item for key, item in payload.items()}


def _submitted_answers(arguments: Mapping[str, object]) -> tuple[str, ...]:
    raw = arguments.get("answers")
    if not isinstance(raw, list):
        return ()
    return tuple(str(value) for value in raw)


def _confirmed(expected: tuple[str, ...], outputs: Sequence[str]) -> bool:
    evidence = set(_TOKEN.findall(" ".join(outputs).casefold()))
    return bool(expected) and all(
        set(_TOKEN.findall(value.casefold())) <= evidence for value in expected
    )
