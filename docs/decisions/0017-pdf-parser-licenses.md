# PDF and office parsers

Digital PDF text uses pypdfium2, the library named in the specification. Pillow
is a dependency of that library. Its declared license is MIT-CMU, and the
license text grants use, copy, modification, and distribution without fee.
pypdfium2 declares `BSD-3-Clause, Apache-2.0, dependency licenses`: the wrapper
is Apache-2.0 and BSD-3-Clause, and the wheel ships an unmodified PDFium build
together with that build's dependency notices. Both are recorded as allow-list
exceptions. The documentation of pypdfium2 is CC-BY-4.0 and is not shipped.

A page with no text layer is rendered and passed to the OCR engine. Tests
inject a fake engine. The Tesseract wrapper runs only when the `tesseract`
binary is installed, so CI does not need it.

DOCX and HTML do not go through docling in this task. docling's only direct
requirement is `docling-slim[standard]`, an ML distribution whose license tree
was not reviewed as one permissive library. A DOCX paragraph and an HTML text
run therefore keep a page number and use the paragraph or run index as the
coordinate, which is the substitute the specification allows when a format has
no coordinates. PPTX, XLSX, and complex layout stay with docling once that
tree is accepted.
