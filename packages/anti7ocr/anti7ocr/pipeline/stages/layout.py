"""Layout stage."""

from __future__ import annotations

from ...models import LayoutResult
from ...text_ops import normalize_text, transform_text_to_tokens, wrap_tokens


class LayoutStage:
    """Build glyph tokens and line assignment."""

    name = "layout"

    def __call__(self, ctx):
        text_cfg = ctx.config["text"]
        layout_cfg = ctx.config["layout"]
        normalized = normalize_text(ctx.text, text_cfg.get("unicode_normalization", "NFC"))
        tokens = transform_text_to_tokens(
            normalized,
            rng=ctx.py_rng,
            char_to_pinyin_ratio=float(text_cfg.get("char_to_pinyin_ratio", 0.0)),
            char_reverse_ratio=float(text_cfg.get("char_reverse_ratio", 0.0)),
            reverse_rotation_range=tuple(text_cfg.get("reverse_rotation_range", [170, 190])),
            enable_char_to_pinyin=bool(text_cfg.get("enable_char_to_pinyin", False)),
            enable_char_reverse=bool(text_cfg.get("enable_char_reverse", False)),
        )
        direction = str(layout_cfg.get("direction", "horizontal"))
        wrapped, lines = wrap_tokens(
            tokens,
            int(layout_cfg.get("max_chars_per_line", 0)),
            direction=direction,
            max_chars_per_column=int(layout_cfg.get("max_chars_per_column", 20)),
        )

        for token in wrapped:
            token.kerning_jitter = ctx.py_rng.uniform(
                -float(layout_cfg.get("micro_kerning_jitter", 0.0)),
                float(layout_cfg.get("micro_kerning_jitter", 0.0)),
            )
            token.baseline_jitter = ctx.py_rng.uniform(
                -float(layout_cfg.get("baseline_jitter", 0.0)),
                float(layout_cfg.get("baseline_jitter", 0.0)),
            )
            token.scale_jitter = ctx.py_rng.uniform(
                -float(layout_cfg.get("character_scale_jitter", 0.0)),
                float(layout_cfg.get("character_scale_jitter", 0.0)),
            )

        ctx.layout = LayoutResult(tokens=wrapped, lines=lines)
        ctx.metadata["line_count"] = len(lines)
        return ctx

