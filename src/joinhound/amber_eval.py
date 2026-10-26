# SPDX-License-Identifier: Apache-2.0

"""Build a compact database-and-files evaluation from the CC0 AmbER sets."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from joinhound.core.uri import PgUri, S3Uri, build_uri

AMBER_COMMIT = "fc8415e411998a6232b5cb9f0f71f29b7591b6af"
AMBER_URL = (
    "https://raw.githubusercontent.com/anthonywchen/AmbER-Sets/"
    f"{AMBER_COMMIT}/data/human/amber_set_tuples.jsonl"
)
AMBER_SHA256 = "fcdb182a4148a40bca9f9ca12a9f0bc599e729d48879869d4695ad13f1225e17"
DEFAULT_SETS = 50
DOCUMENT_COLLECTION = "s3://amber-dossiers/"
SOURCE = "amber"

QuestionSplit = Literal["dev", "test"]
QuestionKind = Literal["head", "tail"]

_NORMALIZE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class AmberFact:
    """One single-valued Wikidata property from an AmbER entity."""

    property_id: str
    property_name: str
    aliases: tuple[str, ...]

    @property
    def answer(self) -> str:
        """Return the canonical answer used by the benchmark."""
        return self.aliases[0]


@dataclass(frozen=True)
class AmberEntity:
    """One entity that shares its displayed name with at least one other entity."""

    qid: str
    name: str
    is_head: bool
    popularity: float
    facts: tuple[AmberFact, ...]


@dataclass(frozen=True)
class AmberCase:
    """A dossier whose clue resolves an ambiguous entity without exposing its QID."""

    case_id: int
    dossier_ref: str
    entity: AmberEntity
    clue: AmberFact
    clue_alias: str
    target: AmberFact
    split: QuestionSplit


@dataclass(frozen=True)
class AmberQuestion:
    """One answer question with gold source URIs."""

    id: str
    split: QuestionSplit
    kind: QuestionKind
    query: str
    answers: tuple[str, ...]
    evidence: tuple[str, ...]


def load_sets(path: Path, count: int = DEFAULT_SETS) -> list[list[AmberEntity]]:
    """Select balanced ambiguous-name sets with usable clues and targets."""
    if count <= 0 or count % 2:
        raise ValueError("Set count must be a positive even number")
    candidates = [_parse_set(line) for line in path.read_text(encoding="utf-8").splitlines()]
    candidates = [entities for entities in candidates if _has_head_and_tail(entities)]
    frequencies = _alias_frequencies(candidates)
    usable = [
        entities for entities in candidates if _has_usable_head_and_tail(entities, frequencies)
    ]
    usable.sort(key=lambda entities: (entities[0].name.casefold(), entities[0].name))
    if len(usable) < count:
        raise ValueError(f"AmbER yielded {len(usable)} usable sets, expected {count}")
    half = count // 2
    return [*usable[:half], *usable[-half:]]


def cases(sets: list[list[AmberEntity]]) -> list[AmberCase]:
    """Choose one head and one tail dossier from every ambiguous-name set."""
    frequencies = _alias_frequencies(sets)
    result: list[AmberCase] = []
    for set_index, entities in enumerate(sets):
        split: QuestionSplit = "dev" if set_index < len(sets) // 2 else "test"
        for is_head in (True, False):
            eligible = [
                entity
                for entity in entities
                if entity.is_head is is_head and _clue_candidates(entity, frequencies)
            ]
            entity = sorted(eligible, key=lambda item: item.qid)[0]
            clue = _clue_candidates(entity, frequencies)[0]
            clue_alias = min(
                (
                    alias
                    for alias in clue.aliases
                    if len(_normalize(alias)) >= 4 and frequencies[_normalize(alias)] <= 10
                ),
                key=lambda alias: (frequencies[_normalize(alias)], -len(alias), alias.casefold()),
            )
            target = sorted(
                (fact for fact in entity.facts if fact.property_id != clue.property_id),
                key=lambda fact: (fact.property_id, fact.property_name),
            )[0]
            case_id = len(result) + 1
            result.append(
                AmberCase(
                    case_id=case_id,
                    dossier_ref=f"AMBER-{case_id:05d}",
                    entity=entity,
                    clue=clue,
                    clue_alias=clue_alias,
                    target=target,
                    split=split,
                )
            )
    return result


def write_bundle(
    root: Path,
    selected: list[AmberCase],
    fact_ids: dict[tuple[str, str], int],
    *,
    distort: bool = False,
) -> None:
    """Write dossiers, questions, and source metadata."""
    files = root / "files"
    files.mkdir(parents=True, exist_ok=True)
    questions: list[AmberQuestion] = []
    for case in selected:
        path = files / f"dossier-{case.case_id:05d}.txt"
        path.write_text(dossier_body(case, distort=distort), encoding="utf-8")
        questions.append(
            AmberQuestion(
                id=f"{case.split}-{case.dossier_ref.casefold()}",
                split=case.split,
                kind="head" if case.entity.is_head else "tail",
                query=(
                    f"According to dossier {case.dossier_ref}, what is the subject's "
                    f"{case.target.property_name}?"
                ),
                answers=(case.target.answer,),
                evidence=(
                    dossier_uri(case),
                    _row_uri("amber_facts", fact_ids[(case.entity.qid, case.target.property_id)]),
                ),
            )
        )
    _write_json(root / "questions.json", {"questions": [asdict(item) for item in questions]})
    _write_json(
        root / "manifest.json",
        {
            "dataset": "AmbER Sets human tuples",
            "license": "CC0-1.0",
            "source_url": AMBER_URL,
            "source_sha256": AMBER_SHA256,
            "source_commit": AMBER_COMMIT,
            "sets": len(selected) // 2,
            "dossiers": len(selected),
            "questions": len(questions),
            "clues": "distorted" if distort else "exact",
        },
    )


def load_questions(path: Path) -> list[AmberQuestion]:
    """Read questions written by :func:`write_bundle`."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        AmberQuestion(
            id=str(item["id"]),
            split=item["split"],
            kind=item["kind"],
            query=str(item["query"]),
            answers=tuple(str(value) for value in item["answers"]),
            evidence=tuple(str(value) for value in item["evidence"]),
        )
        for item in payload["questions"]
    ]


def dossier_body(case: AmberCase, *, distort: bool = False) -> str:
    """Render a clue without the entity's QID or target answer."""
    return (
        f"Ambiguous entity dossier\nReference: {case.dossier_ref}\n"
        f"Subject name: {case.entity.name}\n"
        f"Known {case.clue.property_name}: {_clue_surface(case, distort)}\n"
        "The source entity identifier is intentionally omitted.\n"
    )


def distort_alias(value: str) -> str:
    """Strip diacritics and transpose two letters so the clue is not an exact alias."""
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    characters = list(folded)
    indexes = [index for index, character in enumerate(characters) if character.isalpha()]
    if len(indexes) >= 2:
        left = indexes[len(indexes) // 2 - 1]
        right = indexes[len(indexes) // 2]
        characters[left], characters[right] = characters[right], characters[left]
    distorted = "".join(characters)
    if distorted.casefold() == value.casefold() and indexes:
        del characters[indexes[len(indexes) // 2]]
        distorted = "".join(characters)
    return distorted


def _clue_surface(case: AmberCase, distort: bool) -> str:
    alias = case.clue_alias
    if distort and len(alias) < 8:
        longer = [
            item
            for item in case.clue.aliases
            if len(item) >= 8 and item.casefold() != case.target.answer.casefold()
        ]
        if longer:
            alias = max(longer, key=len)
    if not distort:
        return alias
    return distort_alias(alias)


def dossier_uri(case: AmberCase) -> str:
    """Return the provenance URI for a dossier."""
    return build_uri(S3Uri(source="amber-dossiers", key=f"dossier-{case.case_id:05d}.txt"))


def sha256(path: Path) -> str:
    """Return a file's SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_set(line: str) -> list[AmberEntity]:
    raw = json.loads(line)
    result: list[AmberEntity] = []
    for qid, entity in raw["qids"].items():
        facts: list[AmberFact] = []
        for property_id, fact in entity["pids"].items():
            values: list[tuple[str, ...]] = []
            for value in fact["values"]:
                aliases = _unique_strings(
                    [*value.get("aliases", []), *value.get("additional_aliases", [])]
                )
                if aliases:
                    values.append(aliases)
            if len(values) == 1:
                facts.append(
                    AmberFact(
                        property_id=property_id,
                        property_name=str(fact["property"]),
                        aliases=values[0],
                    )
                )
        if len(facts) >= 2:
            result.append(
                AmberEntity(
                    qid=str(qid),
                    name=str(raw["name"]),
                    is_head=bool(entity["is_head"]),
                    popularity=float(entity["popularity"]),
                    facts=tuple(facts),
                )
            )
    return result


def _has_head_and_tail(entities: list[AmberEntity]) -> bool:
    return any(entity.is_head for entity in entities) and any(
        not entity.is_head for entity in entities
    )


def _has_usable_head_and_tail(entities: list[AmberEntity], frequencies: Counter[str]) -> bool:
    return any(
        entity.is_head and _clue_candidates(entity, frequencies) for entity in entities
    ) and any(not entity.is_head and _clue_candidates(entity, frequencies) for entity in entities)


def _clue_candidates(entity: AmberEntity, frequencies: Counter[str]) -> list[AmberFact]:
    candidates = [
        fact
        for fact in entity.facts
        if any(
            len(_normalize(alias)) >= 4 and frequencies[_normalize(alias)] <= 10
            for alias in fact.aliases
        )
    ]
    return sorted(
        candidates,
        key=lambda fact: (
            min(
                frequencies[_normalize(alias)]
                for alias in fact.aliases
                if len(_normalize(alias)) >= 4
            ),
            fact.property_id,
        ),
    )


def _alias_frequencies(sets: list[list[AmberEntity]]) -> Counter[str]:
    return Counter(
        _normalize(alias)
        for entities in sets
        for entity in entities
        for fact in entity.facts
        for alias in fact.aliases
        if len(_normalize(alias)) >= 4
    )


def _normalize(value: str) -> str:
    return _NORMALIZE.sub(" ", value.casefold()).strip()


def _unique_strings(values: list[object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(value).strip() for value in values if isinstance(value, str) and value.strip()
        )
    )


def _row_uri(table: str, row_id: int) -> str:
    return build_uri(PgUri(source=SOURCE, schema="public", table=table, pk={"id": row_id}))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
