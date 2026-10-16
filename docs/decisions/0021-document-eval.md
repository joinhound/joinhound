# Document evaluation set

The stage 3 corpus is generated, not stored as PDF bytes. `joinhound.evalset` builds two hundred PDFs and the fifty gold questions. Forty pages have an empty content stream so they exercise the scan path without a Tesseract binary in CI.

Gold comparison uses the object key. A passage URI carries a page and a box that the parser assigns, and those coordinates are not part of the question's identity.

PDF lines are grouped by vertical overlap. A shared baseline split punctuation such as `@` and `.` onto their own lines and concatenated the remaining glyphs. Overlap keeps one visual line together.

`get_context` on this set is the stage 3 measurement. Recall is 0.8 because the ten scan questions have no text to find. A model was not called.
