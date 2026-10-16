# SPDX-License-Identifier: Apache-2.0

"""Read visible HTML text. The element order stands in for a box."""

from __future__ import annotations

from html.parser import HTMLParser

from joinhound.core.models import TextBlock


class HtmlParser:
    """HTML documents."""

    mime_types = ("text/html",)

    def parse(self, data: bytes) -> list[TextBlock]:
        """Return one block per visible text run."""
        collector = _Collector()
        collector.feed(data.decode("utf-8", errors="replace"))
        blocks: list[TextBlock] = []
        for number, text in enumerate(collector.parts, start=1):
            index = float(number)
            blocks.append(TextBlock(text=text, page=1, bbox=(index, 0.0, index, 1.0)))
        return blocks


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text and not self._skip:
            self.parts.append(text)
