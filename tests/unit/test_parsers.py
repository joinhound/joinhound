# SPDX-License-Identifier: Apache-2.0

"""Parsers attach a page and a bounding box to every block."""

import io
import zipfile
from xml.etree import ElementTree

import pypdfium2 as pdfium

from joinhound.core.models import TextBlock
from joinhound.parsers import DocxParser, HtmlParser, PdfParser

_HELLO = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 68>>stream\n"
    b"BT /F1 18 Tf 20 100 Td (HELLO WORLD) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 6\n"
    b"0000000000 65535 f \n"
    b"trailer<</Size 6/Root 1 0 R>>\n"
    b"startxref\n0\n%%EOF\n"
)


class _FakeOcr:
    def recognize(self, image: bytes) -> str:
        assert image.startswith(b"\x89PNG")
        return "SCANNED PAGE"


def test_pdf_keeps_an_email_on_one_line() -> None:
    from joinhound.evalset import _pdf

    blocks = PdfParser().parse(_pdf("Invoice INV-1000 for Ada ada@example.com"))

    assert len(blocks) == 1
    assert "INV-1000" in blocks[0].text
    assert "ada@example.com" in blocks[0].text


def test_pdf_text_has_page_and_box() -> None:
    blocks = PdfParser().parse(_HELLO)
    assert len(blocks) == 1
    block = blocks[0]
    assert block.text == "HELLO WORLD"
    assert block.page == 1
    left, bottom, right, top = block.bbox
    assert left < right
    assert bottom < top


def test_blank_pdf_uses_ocr() -> None:
    document = pdfium.PdfDocument.new()
    document.new_page(200, 200)
    buffer = io.BytesIO()
    document.save(buffer)
    blocks = PdfParser(ocr=_FakeOcr()).parse(buffer.getvalue())
    assert blocks == [TextBlock(text="SCANNED PAGE", page=1, bbox=(0.0, 0.0, 200.0, 200.0))]


def test_docx_paragraphs_are_numbered() -> None:
    blocks = DocxParser().parse(_docx("First paragraph", "Second paragraph"))
    assert [block.text for block in blocks] == ["First paragraph", "Second paragraph"]
    assert blocks[0].page == 1
    assert blocks[0].bbox == (1.0, 0.0, 1.0, 1.0)
    assert blocks[1].bbox[0] == 2.0


def test_html_skips_script() -> None:
    page = b"<html><script>secret</script><p>Visible</p></html>"
    blocks = HtmlParser().parse(page)
    assert [block.text for block in blocks] == ["Visible"]
    assert blocks[0].page == 1
    assert len(blocks[0].bbox) == 4


def _docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    ElementTree.fromstring(document)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()
