"""Font discovery and fallback helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import ImageFont


FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".woff2"}


class FontManager:
    """Loads and chooses fonts for glyph rendering."""

    def __init__(self, *, paths: Iterable[str], directories: Iterable[str], fallback_to_default: bool = True):
        self.font_paths: list[Path] = []
        for value in paths:
            path = Path(value).expanduser().resolve()
            if path.is_file():
                self.font_paths.append(path)
        for directory in directories:
            root = Path(directory).expanduser().resolve()
            if not root.is_dir():
                continue
            for file in sorted(root.rglob("*")):
                if file.suffix.lower() in FONT_EXTENSIONS:
                    self.font_paths.append(file.resolve())
        dedup: dict[str, Path] = {str(path): path for path in self.font_paths}
        self.font_paths = list(dedup.values())
        self.fallback_to_default = fallback_to_default

    def has_fonts(self) -> bool:
        return bool(self.font_paths)

    def available_fonts(self) -> list[Path]:
        return list(self.font_paths)

    def inspect_text_coverage(self, text: str, size: int) -> dict:
        missing: dict[str, str] = {}
        for char in text:
            if char == "\n":
                continue
            if self._supports_char(char, size):
                continue
            missing[char] = "missing_glyph"
        return {"missing_chars": sorted(set(missing.keys())), "count": len(set(missing.keys()))}

    def get_font(self, char: str, size: int):
        for path in self.font_paths:
            try:
                font = ImageFont.truetype(str(path), size)
            except OSError:
                continue
            if _font_supports_char(font, char):
                return font
        if self.fallback_to_default:
            try:
                return ImageFont.load_default(size=max(8, size))
            except TypeError:
                return ImageFont.load_default()
        raise RuntimeError(f"No available font supports char {char!r}")

    def _supports_char(self, char: str, size: int) -> bool:
        if not self.font_paths and self.fallback_to_default:
            return True
        for path in self.font_paths:
            try:
                font = ImageFont.truetype(str(path), size)
            except OSError:
                continue
            if _font_supports_char(font, char):
                return True
        return False


def _font_supports_char(font, char: str) -> bool:
    try:
        mask = font.getmask(char)
    except Exception:
        return False
    return mask.size[0] > 0 and mask.size[1] > 0
