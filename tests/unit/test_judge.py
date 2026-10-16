# SPDX-License-Identifier: Apache-2.0

"""The OpenAI judge uses a recorded response and does not call the network."""

import json

from joinhound.core.models import Candidate, ColumnProfile, JudgeVerdict, LinkDraft
from joinhound.llm.openai_judge import OpenAIJudge
from joinhound.profiler.profile import apply_judge

_VERDICT = json.dumps(
    {
        "is_meaningful": True,
        "relation_name": "order to customer",
        "direction": "forward",
        "cardinality": "N:1",
        "confidence": 0.8,
        "rationale": "The values are the same email.",
    }
)


class _Client:
    def __init__(self, content: str = _VERDICT) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self._content = content
        self.chat = _Chat(self)


class _Chat:
    def __init__(self, client: _Client) -> None:
        self.completions = _Completions(client)


class _Completions:
    def __init__(self, client: _Client) -> None:
        self._client = client

    def create(self, **kwargs: object) -> object:
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        self._client.prompts.append(str(messages[1]["content"]))
        self._client.calls += 1
        return _Response(self._client._content)


class _Response:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


def test_recorded_response_is_cached() -> None:
    client = _Client()
    judge = OpenAIJudge(base_url="http://localhost", api_key="test", client=client)
    candidate = Candidate(match_type="fuzzy", confidence=0.7, evidence={"matches": ["Ada"]})

    first = judge.review(candidate)
    second = judge.review(candidate)

    assert client.calls == 1
    assert first == second
    assert first.relation_name == "order to customer"
    assert first.confidence == 0.8


def test_sensitive_values_are_replaced_by_their_pattern() -> None:
    client = _Client()
    judge = OpenAIJudge(
        redact=True,
        sensitive_columns=["email"],
        client=client,
    )
    judge.review(
        Candidate(
            match_type="fuzzy",
            confidence=0.7,
            evidence={"src_column": "email", "matches": ["ada@example.com"]},
        )
    )

    assert client.calls == 1
    assert "ada@example.com" not in client.prompts[0]
    assert "A@A.A" in client.prompts[0]


def test_a_rejection_drops_the_draft_and_a_high_score_skips_the_judge() -> None:
    client = _Client(
        json.dumps(
            {
                "is_meaningful": False,
                "relation_name": "",
                "direction": "forward",
                "cardinality": "N:1",
                "confidence": 0.1,
                "rationale": "Different domains.",
            }
        )
    )
    judge = OpenAIJudge(client=client)
    src = ColumnProfile(collection_id="orders", column_name="email", type_class="text")
    dst = ColumnProfile(collection_id="customers", column_name="email", type_class="text")
    draft = LinkDraft(
        link_id="orders.email",
        src_collection="orders",
        src_column="email",
        dst_collection="customers",
        dst_column="email",
        match_type="fuzzy",
        origin="discovered",
        confidence=0.7,
        status="proposed",
    )
    candidate = Candidate(match_type="fuzzy", confidence=0.7, evidence={})

    assert apply_judge(judge, candidate, src, dst, draft) is None
    assert client.calls == 1

    certain = candidate.model_copy(update={"confidence": 0.96})
    kept = apply_judge(judge, certain, src, dst, draft)
    assert kept == draft
    assert client.calls == 1


def test_verdict_fields_replace_the_draft() -> None:
    verdict = JudgeVerdict(
        is_meaningful=True,
        relation_name="order to customer",
        direction="forward",
        cardinality="N:1",
        confidence=0.8,
        rationale="Same inbox.",
    )
    client = _Client(verdict.model_dump_json())
    judge = OpenAIJudge(client=client)
    src = ColumnProfile(collection_id="orders", column_name="note", type_class="text")
    dst = ColumnProfile(collection_id="customers", column_name="note", type_class="text")
    draft = LinkDraft(
        link_id="orders.note",
        src_collection="orders",
        src_column="note",
        dst_collection="customers",
        dst_column="note",
        match_type="fuzzy",
        origin="discovered",
        confidence=0.7,
        status="proposed",
    )
    updated = apply_judge(
        judge,
        Candidate(match_type="fuzzy", confidence=0.7, evidence={}),
        src,
        dst,
        draft,
    )

    assert updated is not None
    assert updated.relation_name == "order to customer"
    assert updated.cardinality == "N:1"
    assert updated.confidence == 0.8
