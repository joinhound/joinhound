# SPDX-License-Identifier: Apache-2.0

"""Extract PDF text and bounding boxes with PDFium."""

from __future__ import annotations

import io
from collections.abc import Sequence

import pypdfium2 as pdfium

from joinhound.core.models import TextBlock
from joinhound.core.protocols import OcrEngine

_LINE_GAP = 3.0


class PdfParser:
    """Digital PDF text. A page with no text layer is sent to OCR."""

    mime_types = ("application/pdf",)

    def __init__(self, ocr: OcrEngine | None = None) -> None:
        self._ocr = ocr

    def parse(self, data: bytes) -> list[TextBlock]:
        """Return one block per visual line, with the page and the line box."""
        document = pdfium.PdfDocument(data)
        blocks: list[TextBlock] = []
        try:
            for index in range(len(document)):
                page = document[index]
                text_page = page.get_textpage()
                chars = _characters(text_page)
                if chars:
                    blocks.extend(_lines(chars, index + 1))
                elif self._ocr is not None:
                    blocks.extend(_recognize(page, index + 1, self._ocr))
        finally:
            document.close()
        return blocks


def _characters(text_page: pdfium.PdfTextPage) -> list[tuple[str, float, float, float, float]]:
    found: list[tuple[str, float, float, float, float]] = []
    for index in range(text_page.count_chars()):
        character = text_page.get_text_range(index, 1)
        left, bottom, right, top = text_page.get_charbox(index, loose=False)
        found.append((character, left, bottom, right, top))
    return found


def _lines(
    chars: Sequence[tuple[str, float, float, float, float]],
    page: int,
) -> list[TextBlock]:
    ordered = sorted(chars, key=lambda item: (-item[4], item[1]))
    lines: list[list[tuple[str, float, float, float, float]]] = []
    current = [ordered[0]]
    for item in ordered[1:]:
        if abs(item[2] - current[-1][2]) > _LINE_GAP:
            lines.append(current)
            current = [item]
        else:
            current.append(item)
    lines.append(current)
    blocks: list[TextBlock] = []
    for line in lines:
        ordered_line = sorted(line, key=lambda item: item[1])
        text = "".join(item[0] for item in ordered_line).strip()
        if not text:
            continue
        left = min(item[1] for item in ordered_line)
        bottom = min(item[2] for item in ordered_line)
        right = max(item[3] for item in ordered_line)
        top = max(item[4] for item in ordered_line)
        blocks.append(TextBlock(text=text, page=page, bbox=(left, bottom, right, top)))
    return blocks


def _recognize(page: pdfium.PdfPage, page_number: int, ocr: OcrEngine) -> list[TextBlock]:
    rendered = page.render(scale=2)
    image = rendered.to_pil()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    text = ocr.recognize(buffer.getvalue()).strip()
    if not text:
        return []
    width, height = page.get_size()
    return [TextBlock(text=text, page=page_number, bbox=(0.0, 0.0, width, height))]
