"""Compatibility layer for antiOCR-like API."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple, Union

from PIL import Image

from .api import generate
from .image_ops import to_color
from .text_ops import split_like_antiocr


class AntiOcrCompat:
    """Compatibility wrapper with antiOCR-like call semantics."""

    def __call__(
        self,
        texts: Union[str, List[str]],
        *,
        font_fp: Union[str, Path],
        char_to_pinyin_ratio: float = 0.1,
        char_reverse_ratio: float = 0.1,
        min_font_size: int = 15,
        max_font_size: int = 60,
        text_color: Union[str, int, Tuple[int, int, int]] = "black",
        bg_image: Optional[Union[str, Path, Image.Image]] = None,
        bg_gen_config: Optional[dict] = None,
        seed: int | None = None,
        **kwargs,
    ) -> Image.Image:
        if isinstance(texts, list):
            text = "\n".join(texts)
        else:
            text = texts
        bg_cfg = {"enable": bg_image is None}
        bg_cfg.update(bg_gen_config or {})
        cfg = {
            "text": {
                "enable_char_to_pinyin": True,
                "char_to_pinyin_ratio": char_to_pinyin_ratio,
                "enable_char_reverse": True,
                "char_reverse_ratio": char_reverse_ratio,
            },
            "font": {
                "paths": [str(font_fp)],
                "directories": [],
                "min_size": min_font_size,
                "max_size": max_font_size,
            },
            "canvas": {"text_color": list(to_color(text_color))},
            "background": bg_cfg,
        }
        output = generate(
            text=text,
            config=cfg,
            seed=seed,
            output_options={"background_image": _load_bg_image(bg_image)} if bg_image is not None else None,
        )
        return output.image

    @classmethod
    def split(cls, texts: str) -> list[dict]:
        return split_like_antiocr(texts)

    @classmethod
    def transform(cls, texts: list[dict], char_to_pinyin_ratio: float, char_reverse_ratio: float) -> list[dict]:
        import random
        from pypinyin import lazy_pinyin

        outs: list[dict] = []
        for info in texts:
            chunk = info.get("char", "")
            chunk_type = info.get("type", "cn")
            reverse = False
            if random.random() < char_to_pinyin_ratio:
                chunk = "".join(lazy_pinyin(chunk))
                chunk_type = "pinyin"
            elif chunk_type == "cn":
                reverse = random.random() < char_reverse_ratio
            outs.append({"char": chunk, "type": chunk_type, "reverse": reverse})
        return outs


class AntiOcr(AntiOcrCompat):
    """Alias to simplify migration from antiocr.AntiOcr."""


def _load_bg_image(bg_image: Union[str, Path, Image.Image]) -> Image.Image:
    if isinstance(bg_image, Image.Image):
        return bg_image
    return Image.open(bg_image)
