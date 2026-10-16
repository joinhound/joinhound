# SPDX-License-Identifier: Apache-2.0

"""Turn extracted blocks into passages of a few hundred tokens."""

from __future__ import annotations

import unicodedata
from collections import Counter

import tiktoken

from joinhound.core.models import TextBlock

_ENCODER = tiktoken.get_encoding("cl100k_base")
_MIN_TOKENS = 300
_MAX_TOKENS = 500
_OVERLAP_TOKENS = 50


def normalize_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    """Normalize text, join end-of-line hyphens, and drop repeated page furniture."""
    normalized = [
        block.model_copy(update={"text": unicodedata.normalize("NFKC", block.text).strip()})
        for block in blocks
    ]
    normalized = [block for block in normalized if block.text]
    return _drop_repeated(list(_join_hyphens(normalized)))


def chunk_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    """Pack blocks into passages of 300–500 tokens, overlapping by about 50.

    A passage stays on one page and never splits a block. A block longer than
    500 tokens is its own passage. The last passage of a page may be shorter.
    """
    passages: list[TextBlock] = []
    for page in sorted({block.page for block in blocks}):
        page_blocks = [block for block in blocks if block.page == page]
        passages.extend(_chunk_page(page_blocks))
    return passages


def _join_hyphens(blocks: list[TextBlock]) -> list[TextBlock]:
    merged: list[TextBlock] = []
    index = 0
    while index < len(blocks):
        current = blocks[index]
        index += 1
        while (
            index < len(blocks)
            and current.page == blocks[index].page
            and current.text.endswith("-")
            and blocks[index].text[:1].islower()
        ):
            nxt = blocks[index]
            current = TextBlock(
                text=current.text[:-1] + nxt.text,
                page=current.page,
                bbox=_union((current, nxt)),
            )
            index += 1
        merged.append(current)
    return merged


def _drop_repeated(blocks: list[TextBlock]) -> list[TextBlock]:
    pages = {block.page for block in blocks}
    if len(pages) < 2:
        return blocks
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({block.text for block in blocks if block.page == page})
    threshold = 0.8 * len(pages)
    repeated = {text for text, count in counts.items() if count >= threshold}
    return [block for block in blocks if block.text not in repeated]


def _chunk_page(blocks: list[TextBlock]) -> list[TextBlock]:
    passages: list[TextBlock] = []
    start = 0
    while start < len(blocks):
        end = _take(blocks, start)
        passages.append(_passage(blocks[start:end]))
        if end >= len(blocks):
            break
        start = _overlap_start(blocks, start, end)
    return passages


def _take(blocks: list[TextBlock], start: int) -> int:
    end = start + 1
    while end < len(blocks):
        if _tokens(_join(blocks[start : end + 1])) > _MAX_TOKENS:
            break
        end += 1
    return end


def _overlap_start(blocks: list[TextBlock], start: int, end: int) -> int:
    if end == start + 1:
        return end
    back = end
    while back > start + 1:
        back -= 1
        if _tokens(_join(blocks[back:end])) >= _OVERLAP_TOKENS:
            return back
    return back


def _passage(blocks: list[TextBlock]) -> TextBlock:
    return TextBlock(text=_join(blocks), page=blocks[0].page, bbox=_union(blocks))


def _join(blocks: list[TextBlock]) -> str:
    return " ".join(block.text for block in blocks)


def _union(blocks: tuple[TextBlock, ...] | list[TextBlock]) -> tuple[float, float, float, float]:
    return (
        min(block.bbox[0] for block in blocks),
        min(block.bbox[1] for block in blocks),
        max(block.bbox[2] for block in blocks),
        max(block.bbox[3] for block in blocks),
    )


def _tokens(text: str) -> int:
    return len(_ENCODER.encode(text))
