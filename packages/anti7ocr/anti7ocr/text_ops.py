"""Text normalization and anti-OCR compatibility transforms."""

from __future__ import annotations

import string
import unicodedata
from typing import Iterable

from pypinyin import lazy_pinyin

from .models import GlyphToken

_ENG_LETTERS = set(string.digits + string.ascii_letters + string.punctuation + " ")


def normalize_text(text: str, mode: str = "NFC") -> str:
    return unicodedata.normalize(mode, text)


def is_cjk_char(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0xF900 <= code <= 0xFAFF
    )


def split_like_antiocr(text: str) -> list[dict]:
    """Split text into antiOCR-like cn/en chunks."""

    if not text:
        return []
    parts: list[dict] = []
    start = 0
    current_type = "en" if text[0] in _ENG_LETTERS else "cn"
    for idx, char in enumerate(text):
        candidate_type = "en" if char in _ENG_LETTERS else "cn"
        if candidate_type == current_type:
            continue
        parts.append({"char": text[start:idx], "type": current_type})
        start = idx
        current_type = candidate_type
    parts.append({"char": text[start:], "type": current_type})
    return parts


def transform_text_to_tokens(
    text: str,
    *,
    rng,
    char_to_pinyin_ratio: float,
    char_reverse_ratio: float,
    reverse_rotation_range: tuple[int, int],
    enable_char_to_pinyin: bool,
    enable_char_reverse: bool,
) -> list[GlyphToken]:
    """Transform plain text into tokens with antiOCR-style behavior."""

    tokens: list[GlyphToken] = []
    for char in text:
        if char == "\n":
            tokens.append(GlyphToken(char=char))
            continue
        if enable_char_to_pinyin and is_cjk_char(char) and rng.random() < char_to_pinyin_ratio:
            pinyin = "".join(lazy_pinyin(char))
            for pchar in pinyin:
                tokens.append(GlyphToken(char=pchar))
            continue

        reverse = bool(
            enable_char_reverse and is_cjk_char(char) and rng.random() < char_reverse_ratio
        )
        rotation = float(rng.randint(reverse_rotation_range[0], reverse_rotation_range[1])) if reverse else 0.0
        tokens.append(GlyphToken(char=char, reverse=reverse, rotation=rotation))
    return tokens


def wrap_tokens(
    tokens: Iterable[GlyphToken],
    max_chars_per_line: int,
    direction: str = "horizontal",
    max_chars_per_column: int = 20,
) -> tuple[list[GlyphToken], list[str]]:
    if direction == "vertical":
        return _wrap_tokens_vertical(tokens, max_chars_per_column)
    return _wrap_tokens_horizontal(tokens, max_chars_per_line)


def _wrap_tokens_horizontal(
    tokens: Iterable[GlyphToken], max_chars_per_line: int
) -> tuple[list[GlyphToken], list[str]]:
    line_index = 0
    char_count = 0
    lines: list[list[str]] = [[]]
    wrapped: list[GlyphToken] = []
    for token in tokens:
        if token.char == "\n":
            line_index += 1
            char_count = 0
            lines.append([])
            continue
        if max_chars_per_line > 0 and char_count >= max_chars_per_line:
            line_index += 1
            char_count = 0
            lines.append([])
        token.line_index = line_index
        token.char_index = char_count
        wrapped.append(token)
        lines[line_index].append(token.char)
        char_count += 1
    line_strings = ["".join(chars) for chars in lines if chars]
    return wrapped, line_strings


def _wrap_tokens_vertical(
    tokens: Iterable[GlyphToken], max_chars_per_column: int
) -> tuple[list[GlyphToken], list[str]]:
    """Wrap tokens into vertical columns (top-to-bottom, right-to-left).

    ``line_index`` represents the column number (0 = rightmost column).
    ``char_index`` represents the position within the column (0 = topmost).
    """
    column_index = 0
    char_count = 0
    columns: list[list[str]] = [[]]
    wrapped: list[GlyphToken] = []
    for token in tokens:
        if token.char == "\n":
            column_index += 1
            char_count = 0
            columns.append([])
            continue
        if max_chars_per_column > 0 and char_count >= max_chars_per_column:
            column_index += 1
            char_count = 0
            columns.append([])
        token.line_index = column_index
        token.char_index = char_count
        wrapped.append(token)
        columns[column_index].append(token.char)
        char_count += 1
    column_strings = ["".join(chars) for chars in columns if chars]
    return wrapped, column_strings

