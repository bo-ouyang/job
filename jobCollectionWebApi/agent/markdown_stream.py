"""Losslessly split validated Markdown into bounded SSE message deltas."""

import re
import unicodedata
from typing import List, Optional


_PARAGRAPH_BOUNDARY = re.compile(r"\n[ \t]*\n+")
_LINE_BOUNDARY = re.compile(r"\n")
_SENTENCE_BOUNDARY = re.compile(r"[.!?。！？；;]+[\"'”’）)\]]*[ \t]*")
_WORD_BOUNDARY = re.compile(r"[ \t]+")


def chunk_markdown(markdown: str, *, max_chars: int = 256) -> List[str]:
    """Return non-empty, ordered chunks whose concatenation is ``markdown``.

    Paragraph and line boundaries are preferred so Markdown headings and lists
    remain readable while they arrive. Sentence and word boundaries are used
    next, with a Unicode-aware hard cut as the final fallback. Blank answers do
    not create stream events.
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    if not markdown or not markdown.strip():
        return []

    chunks: List[str] = []
    position = 0
    length = len(markdown)
    while position < length:
        window_end = min(position + max_chars, length)
        cut = _preferred_cut(markdown, position, window_end)
        if cut is None:
            cut = _unicode_safe_cut(markdown, position, window_end)

        chunk = markdown[position:cut]
        if not chunk.strip():
            # Meaningful Markdown never needs a whitespace-only delta. Attach
            # an otherwise trailing whitespace tail to the preceding chunk.
            if chunks and len(chunks[-1]) + len(chunk) <= max_chars:
                chunks[-1] += chunk
                position = cut
                continue
            cut = _unicode_safe_cut(markdown, position, window_end)
            chunk = markdown[position:cut]
        chunks.append(chunk)
        position = cut

    return chunks


def _preferred_cut(text: str, start: int, window_end: int) -> Optional[int]:
    """Choose the furthest boundary of the highest-priority available kind."""

    text_end = len(text)
    for pattern in (
        _PARAGRAPH_BOUNDARY,
        _LINE_BOUNDARY,
        _SENTENCE_BOUNDARY,
        _WORD_BOUNDARY,
    ):
        candidates = [
            match.end()
            for match in pattern.finditer(text, start, window_end)
            if start < match.end() < text_end
            and text[start : match.end()].strip()
            and text[match.end() :].strip()
        ]
        if candidates:
            return candidates[-1]
    if window_end == text_end:
        return text_end
    return None


def _unicode_safe_cut(text: str, start: int, window_end: int) -> int:
    """Avoid cutting before combining marks or inside common emoji joiners."""

    cut = window_end
    while cut > start and cut < len(text):
        next_character = text[cut]
        previous_character = text[cut - 1]
        if (
            unicodedata.combining(next_character)
            or next_character in {"\ufe0e", "\ufe0f"}
            or "\U0001f3fb" <= next_character <= "\U0001f3ff"
            or previous_character == "\u200d"
        ):
            cut -= 1
            continue
        if previous_character == "\r" and next_character == "\n":
            cut -= 1
            continue
        break
    return cut if cut > start else window_end
