# SPDX-License-Identifier: Apache-2.0

"""Large, reproducible library benchmark shared by preparation and scoring."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from joinhound.core.uri import PgUri, S3Uri, build_uri

DATASET_URL = (
    "https://database-sample-website.s3.eu-north-1.amazonaws.com/"
    "datasets/library-sample-database/v2/flagship/100k/postgres.sql.gz"
)
DATASET_SHA256 = "104b9998bb85c55d0e8190b125cb0a1dff62d4bf628c266013b7568668befa3d"
DATASET_ROWS = 176_780
DEFAULT_DOCUMENTS = 10_000
DEFAULT_QUESTIONS = 500
SOURCE = "library"
DOCUMENT_COLLECTION = "s3://library-cases/"

_ANSWER = re.compile(r"[^a-z0-9]+")
_COLORS = (
    "amber",
    "azure",
    "bronze",
    "coral",
    "crimson",
    "emerald",
    "indigo",
    "ivory",
    "jade",
    "lilac",
    "ochre",
    "olive",
    "pearl",
    "ruby",
    "saffron",
    "scarlet",
    "silver",
    "teal",
    "umber",
    "violet",
    "white",
    "yellow",
)
_OBJECTS = (
    "anchor",
    "badge",
    "bell",
    "compass",
    "feather",
    "harbor",
    "key",
    "lantern",
    "maple",
    "notebook",
    "orchid",
    "quill",
    "ribbon",
    "sail",
    "telescope",
    "violin",
    "willow",
    "window",
    "wren",
    "yarn",
    "zephyr",
    "zinnia",
)
_PLACES = (
    "arcade",
    "archive",
    "atrium",
    "balcony",
    "courtyard",
    "foyer",
    "gallery",
    "garden",
    "hallway",
    "landing",
    "lobby",
    "mezzanine",
    "reading room",
    "rotunda",
    "stairwell",
    "study",
    "terrace",
    "vestibule",
    "west desk",
    "east desk",
    "north desk",
    "south desk",
)


QuestionKind = Literal[
    "database",
    "document",
    "cross_member",
    "cross_book",
    "cross_branch",
    "paraphrase_member",
    "paraphrase_book",
    "conflict_member",
    "cross_staff",
    "cross_publisher",
]
QuestionSplit = Literal["dev", "test"]
STANDARD_KINDS: tuple[QuestionKind, ...] = (
    "database",
    "document",
    "cross_member",
    "cross_book",
    "cross_branch",
)
HARD_KINDS: tuple[QuestionKind, ...] = (
    "paraphrase_member",
    "paraphrase_book",
    "conflict_member",
    "cross_staff",
    "cross_publisher",
)
HARD_QUESTIONS = 250


@dataclass(frozen=True)
class LibraryCase:
    """One generated file and the catalog rows connected to it."""

    case_id: int
    case_ref: str
    loan_id: int
    membership_id: int
    user_id: int
    user_name: str
    copy_id: int
    book_id: int
    book_title: str
    library_id: int
    library_name: str
    card_number: str
    publisher_id: int = 0
    publisher_name: str = ""
    staff_user_id: int = 0
    staff_name: str = ""


@dataclass(frozen=True)
class EvalQuestion:
    """One benchmark question with exact answers and required evidence."""

    id: str
    split: QuestionSplit
    kind: QuestionKind
    query: str
    answers: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class EvalManifest:
    """Pinned inputs and generated benchmark size."""

    dataset_url: str
    dataset_sha256: str
    source_rows: int
    documents: int
    questions: int


def phrase_parts(index: int) -> tuple[str, str, str]:
    """Return the color, object, and place encoded by one case index."""
    capacity = len(_COLORS) * len(_OBJECTS) * len(_PLACES)
    if index < 0 or index >= capacity:
        raise ValueError(f"Case index must be below {capacity}")
    color = _COLORS[index % len(_COLORS)]
    rest = index // len(_COLORS)
    item = _OBJECTS[rest % len(_OBJECTS)]
    place = _PLACES[(rest // len(_OBJECTS)) % len(_PLACES)]
    return color, item, place


def archive_phrase(index: int) -> str:
    """Return a unique, natural-looking phrase for a case file."""
    color, item, place = phrase_parts(index)
    return f"{color} {item} beside the {place}"


def paraphrase(index: int) -> str:
    """Describe the same observation with words that occur in the note, reordered."""
    color, item, place = phrase_parts(index)
    return f"{place} observation {color} {item}"


def case_body(case: LibraryCase) -> str:
    """Render one unstructured circulation note."""
    return (
        "Circulation case note\n"
        f"Reference: {case.case_ref}\n"
        f"Observation: {archive_phrase(case.case_id - 1)}.\n"
        f"{distractor_name(case)} was discussed, but that person did not borrow the copy.\n"
        "The patron asked staff to verify the linked circulation record.\n"
    )


def distractor_name(case: LibraryCase) -> str:
    """Return a personal name that is not an answer for this case."""
    forbidden = {
        value.casefold()
        for value in (
            case.user_name,
            case.book_title,
            case.library_name,
            case.publisher_name,
            case.staff_name,
        )
        if value
    }
    capacity = len(_COLORS) * len(_OBJECTS) * len(_PLACES)
    for shift in range(capacity):
        color, item, _place = phrase_parts((case.case_id * 17 + shift) % capacity)
        name = f"{color.title()} {item.title()}"
        if name.casefold() not in forbidden and not any(
            name.casefold() in answer or answer in name.casefold() for answer in forbidden
        ):
            return name
    raise ValueError(f"No distractor name is distinct for {case.case_ref}")


def case_key(case: LibraryCase) -> str:
    """Return the object key of one generated note."""
    return f"cases/{case.case_ref.casefold()}.txt"


def case_uri(case: LibraryCase) -> str:
    """Return the provenance URI of one generated note."""
    return build_uri(S3Uri(source="library-cases", key=case_key(case)))


def questions(cases: list[LibraryCase], count: int = DEFAULT_QUESTIONS) -> list[EvalQuestion]:
    """Build balanced direct and cross-source questions."""
    if count <= 0 or count % 5:
        raise ValueError("Question count must be a positive multiple of five")
    each = count // 5
    if each % 2:
        raise ValueError("Questions per kind must be even for the dev/test split")
    if len(cases) < each:
        raise ValueError("Not enough cases for the questions")
    half = each // 2
    selected = cases[:half] + cases[-half:]
    result: list[EvalQuestion] = []
    for offset, case in enumerate(selected):
        split: QuestionSplit = "dev" if offset < half else "test"
        phrase = archive_phrase(case.case_id - 1)
        prefix = f"{split}-{case.case_id:05d}"
        file_uri = case_uri(case)
        result.extend(
            [
                EvalQuestion(
                    f"{prefix}-database",
                    split,
                    "database",
                    f"Which member has library card {case.card_number}?",
                    (case.user_name,),
                    (_row_uri("users", case.user_id),),
                ),
                EvalQuestion(
                    f"{prefix}-document",
                    split,
                    "document",
                    f"Which case reference appears in the note mentioning '{phrase}'?",
                    (case.case_ref,),
                    (file_uri,),
                ),
                EvalQuestion(
                    f"{prefix}-member",
                    split,
                    "cross_member",
                    f"Which member is connected to the case note mentioning '{phrase}'?",
                    (case.user_name,),
                    (file_uri, _row_uri("users", case.user_id)),
                ),
                EvalQuestion(
                    f"{prefix}-book",
                    split,
                    "cross_book",
                    f"Which book is connected to the case note mentioning '{phrase}'?",
                    (case.book_title,),
                    (file_uri, _row_uri("books", case.book_id)),
                ),
                EvalQuestion(
                    f"{prefix}-branch",
                    split,
                    "cross_branch",
                    f"Which library branch owns the borrowed copy in the case note mentioning "
                    f"'{phrase}'?",
                    (case.library_name,),
                    (file_uri, _row_uri("libraries", case.library_id)),
                ),
            ]
        )
    return result


def hard_questions(cases: list[LibraryCase], count: int = HARD_QUESTIONS) -> list[EvalQuestion]:
    """Build questions that need a paraphrase, a rejected name, or a longer path."""
    if count <= 0 or count % 5:
        raise ValueError("Question count must be a positive multiple of five")
    each = count // 5
    if each % 2:
        raise ValueError("Questions per kind must be even for the dev/test split")
    eligible = [
        case
        for case in cases
        if case.staff_name
        and case.publisher_name
        and case.staff_name.casefold() != case.user_name.casefold()
        and case.publisher_name.casefold() != case.library_name.casefold()
    ]
    if len(eligible) < each:
        raise ValueError("Not enough cases for the hard questions")
    half = each // 2
    selected = eligible[:half] + eligible[-half:]
    result: list[EvalQuestion] = []
    for offset, case in enumerate(selected):
        split: QuestionSplit = "dev" if offset < half else "test"
        wording = paraphrase(case.case_id - 1)
        prefix = f"hard-{split}-{case.case_id:05d}"
        file_uri = case_uri(case)
        result.extend(
            [
                EvalQuestion(
                    f"{prefix}-member",
                    split,
                    "paraphrase_member",
                    f"Which member borrowed the copy described by '{wording}'?",
                    (case.user_name,),
                    (file_uri, _row_uri("users", case.user_id)),
                ),
                EvalQuestion(
                    f"{prefix}-book",
                    split,
                    "paraphrase_book",
                    f"Which book is connected to the note '{wording}'?",
                    (case.book_title,),
                    (file_uri, _row_uri("books", case.book_id)),
                ),
                EvalQuestion(
                    f"{prefix}-conflict",
                    split,
                    "conflict_member",
                    f"Which member borrowed the copy in the note '{wording}'? "
                    "Ignore any person the note says did not borrow.",
                    (case.user_name,),
                    (file_uri, _row_uri("users", case.user_id)),
                ),
                EvalQuestion(
                    f"{prefix}-staff",
                    split,
                    "cross_staff",
                    f"Which staff member recorded the loan for the note '{wording}'? "
                    "Use the staff record linked from the loan, not the borrowing member.",
                    (case.staff_name,),
                    (file_uri, _row_uri("users", case.staff_user_id)),
                ),
                EvalQuestion(
                    f"{prefix}-publisher",
                    split,
                    "cross_publisher",
                    f"Which publisher issued the book connected to the note '{wording}'?",
                    (case.publisher_name,),
                    (file_uri, _row_uri("publishers", case.publisher_id)),
                ),
            ]
        )
    return result


def write_bundle(
    root: Path,
    cases: list[LibraryCase],
    selected_questions: list[EvalQuestion],
) -> None:
    """Write files, gold questions, and a reproducibility manifest."""
    files = root / "files"
    files.mkdir(parents=True, exist_ok=True)
    for case in cases:
        path = root / "files" / Path(case_key(case)).name
        path.write_text(case_body(case), encoding="utf-8")
    _write_json(
        root / "questions.json", {"questions": [asdict(item) for item in selected_questions]}
    )
    _write_json(
        root / "hard.json",
        {"questions": [asdict(item) for item in hard_questions(cases)]},
    )
    manifest = EvalManifest(
        dataset_url=DATASET_URL,
        dataset_sha256=DATASET_SHA256,
        source_rows=DATASET_ROWS,
        documents=len(cases),
        questions=len(selected_questions),
    )
    _write_json(root / "manifest.json", asdict(manifest))


def load_questions(path: Path) -> list[EvalQuestion]:
    """Read questions written by :func:`write_bundle`."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("Question file must contain a questions list")
    result: list[EvalQuestion] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Question entries must be objects")
        result.append(
            EvalQuestion(
                id=str(item["id"]),
                split=_split(item["split"]),
                kind=_kind(item["kind"]),
                query=str(item["query"]),
                answers=tuple(str(value) for value in item["answers"]),
                evidence=tuple(str(value) for value in item["evidence"]),
            )
        )
    return result


def answer_recall(returned: list[str], expected: tuple[str, ...]) -> float:
    """Return answer recall after normalization, allowing cited details around an answer."""
    actual = [_normalize(value) for value in returned]
    wanted = [_normalize(value) for value in expected]
    hits = sum(any(answer in item for item in actual) for answer in wanted)
    return hits / len(wanted) if wanted else 1.0


def sha256(path: Path) -> str:
    """Return a file's SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_uri(table: str, row_id: int) -> str:
    return build_uri(PgUri(source=SOURCE, schema="public", table=table, pk={"id": row_id}))


def _normalize(value: str) -> str:
    return _ANSWER.sub(" ", value.casefold()).strip()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _split(value: object) -> QuestionSplit:
    if value not in {"dev", "test"}:
        raise ValueError(f"Unknown question split: {value}")
    return value


def _kind(value: object) -> QuestionKind:
    if value not in {*STANDARD_KINDS, *HARD_KINDS}:
        raise ValueError(f"Unknown question kind: {value}")
    return value
