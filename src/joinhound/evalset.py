# SPDX-License-Identifier: Apache-2.0

"""Deterministic invoices, specifications, and letters for the document eval."""

from __future__ import annotations

from dataclasses import dataclass

_NAMES = (
    "Ada Lovelace",
    "Grace Hopper",
    "Alan Turing",
    "Edsger Dijkstra",
)
_EMAILS = (
    "ada@example.com",
    "grace@example.com",
    "alan@example.com",
    "edsger@example.com",
)
_KINDS = ("invoice",) * 80 + ("specification",) * 60 + ("letter",) * 60
_SCAN_INDEXES = frozenset(range(70, 80)) | frozenset(range(130, 140)) | frozenset(range(180, 200))
_DIGITAL_QUESTIONS = tuple(range(10)) + tuple(range(80, 95)) + tuple(range(140, 155))
_SCAN_QUESTIONS = (70, 71, 72, 73, 130, 131, 132, 190, 191, 192)


@dataclass(frozen=True)
class CorpusDocument:
    """One generated PDF and the code it is about."""

    key: str
    kind: str
    code: str
    scan: bool
    text: str | None
    data: bytes


@dataclass(frozen=True)
class CorpusQuestion:
    """A question whose answer is one generated document."""

    id: str
    query: str
    key: str


def generate_corpus() -> tuple[tuple[CorpusDocument, ...], tuple[CorpusQuestion, ...]]:
    """Return 200 PDFs and 50 questions. Forty PDFs have no text layer."""
    documents = tuple(_document(index) for index in range(200))
    questions = tuple(_question(documents[index]) for index in _DIGITAL_QUESTIONS + _SCAN_QUESTIONS)
    return documents, questions


def question_payload(questions: tuple[CorpusQuestion, ...]) -> dict[str, object]:
    """Return the gold file contents for these questions."""
    return {
        "questions": [
            {
                "id": question.id,
                "query": question.query,
                "uris": [f"s3://corpus/{question.key}"],
            }
            for question in questions
        ]
    }


def _document(index: int) -> CorpusDocument:
    kind = _KINDS[index]
    code = _code(index, kind)
    scan = index in _SCAN_INDEXES
    name = _NAMES[index % len(_NAMES)]
    email = _EMAILS[index % len(_EMAILS)]
    text = None if scan else _sentence(kind, code, name, email)
    folder = {"invoice": "invoices", "specification": "specifications", "letter": "letters"}[kind]
    return CorpusDocument(
        key=f"{folder}/{kind}-{index:04d}.pdf",
        kind=kind,
        code=code,
        scan=scan,
        text=text,
        data=_pdf(text),
    )


def _question(document: CorpusDocument) -> CorpusQuestion:
    return CorpusQuestion(
        id=f"{document.kind}-{document.code.lower()}",
        query=document.code,
        key=document.key,
    )


def _code(index: int, kind: str) -> str:
    prefix = {"invoice": "INV", "specification": "SPC", "letter": "LTR"}[kind]
    return f"{prefix}-{1000 + index}"


def _sentence(kind: str, code: str, name: str, email: str) -> str:
    if kind == "invoice":
        return f"Invoice {code} for {name} {email} amount 120.00"
    if kind == "specification":
        return f"Specification {code} for {name} {email} revision 3"
    return f"Letter {code} for {name} {email} regarding delivery"


def _contents(stream: bytes) -> bytes:
    length = str(len(stream)).encode("ascii")
    return b"<< /Length " + length + b" >>\nstream\n" + stream + b"endstream"


def _pdf(text: str | None) -> bytes:
    stream = b""
    if text is not None:
        encoded = text.encode("ascii")
        literal = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        stream = b"BT /F1 18 Tf 20 100 Td (" + literal + b") Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        _contents(stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{number} 0 obj\n".encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(body)
