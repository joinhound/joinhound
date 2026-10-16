# SPDX-License-Identifier: Apache-2.0

"""Read paragraphs from a DOCX file. The paragraph number stands in for a box."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

from joinhound.core.models import TextBlock

_TEXT = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
_PARAGRAPH = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"


class DocxParser:
    """Office Open XML word documents."""

    mime_types = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",)

    def parse(self, data: bytes) -> list[TextBlock]:
        """Return one block per non-empty paragraph."""
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        blocks: list[TextBlock] = []
        number = 0
        for paragraph in root.iter(_PARAGRAPH):
            number += 1
            text = "".join(node.text or "" for node in paragraph.iter(_TEXT)).strip()
            if not text:
                continue
            index = float(number)
            blocks.append(TextBlock(text=text, page=1, bbox=(index, 0.0, index, 1.0)))
        return blocks
