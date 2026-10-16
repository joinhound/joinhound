# SPDX-License-Identifier: Apache-2.0

"""Chunking keeps page coordinates and stays inside the token window."""

import tiktoken

from joinhound.core.models import TextBlock
from joinhound.index.chunks import chunk_blocks, normalize_blocks

_ENCODER = tiktoken.get_encoding("cl100k_base")


def test_passages_stay_inside_the_token_window_and_overlap() -> None:
    blocks = [_block(_words(80), index=float(index)) for index in range(12)]
    passages = chunk_blocks(normalize_blocks(blocks))

    assert len(passages) > 1
    for passage in passages[:-1]:
        count = _tokens(passage.text)
        assert 300 <= count <= 500
    assert _tokens(passages[-1].text) <= 500
    for previous, following in zip(passages, passages[1:], strict=False):
        assert _shared_suffix_tokens(previous.text, following.text) >= 50
        assert previous.page == 1
        assert len(previous.bbox) == 4


def test_a_long_block_is_not_split() -> None:
    text = _words(600)
    passages = chunk_blocks([_block(text)])

    assert len(passages) == 1
    assert passages[0].text == text


def test_end_of_line_hyphen_is_joined() -> None:
    blocks = [_block("recon-", index=0), _block("struct", index=1)]

    normalized = normalize_blocks(blocks)

    assert [block.text for block in normalized] == ["reconstruct"]
    assert normalized[0].bbox == (0.0, 0.0, 2.0, 1.0)


def test_headers_on_most_pages_are_dropped() -> None:
    blocks: list[TextBlock] = []
    for page in range(1, 6):
        blocks.append(_block("Confidential", page=page, index=0))
        blocks.append(_block(f"body {page}", page=page, index=1))

    texts = [block.text for block in normalize_blocks(blocks)]

    assert "Confidential" not in texts
    assert texts == ["body 1", "body 2", "body 3", "body 4", "body 5"]


def test_nfkc_normalizes_compatibility_characters() -> None:
    normalized = normalize_blocks([_block("ﬁle")])

    assert normalized[0].text == "file"


def _block(text: str, *, page: int = 1, index: float = 0) -> TextBlock:
    return TextBlock(text=text, page=page, bbox=(index, 0.0, index + 1.0, 1.0))


def _words(target: int) -> str:
    words = ["alpha"]
    while _tokens(" ".join(words)) < target:
        words.append("alpha")
    while words and _tokens(" ".join(words)) > target:
        words.pop()
    return " ".join(words)


def _tokens(text: str) -> int:
    return len(_ENCODER.encode(text))


def _shared_suffix_tokens(previous: str, following: str) -> int:
    for size in range(min(len(previous), len(following)), 0, -1):
        if previous.endswith(following[:size]):
            return _tokens(following[:size].strip())
    return 0
