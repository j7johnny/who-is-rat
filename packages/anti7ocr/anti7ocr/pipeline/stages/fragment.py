"""Fragment stage."""

from __future__ import annotations

from PIL import ImageDraw

from ...constants import DEFAULT_CLOSED_STRUCTURE_CHARS
from ...image_ops import to_color


class FragmentStage:
    """Apply stroke-level fragmentation."""

    name = "fragment"

    def __call__(self, ctx):
        fragment_cfg = ctx.config.get("fragment", {})
        if not fragment_cfg.get("enable", True) or ctx.render is None or ctx.image is None:
            return ctx

        image = ctx.image.copy()
        draw = ImageDraw.Draw(image)
        bg_color = to_color(ctx.config.get("canvas", {}).get("background_color", [255, 255, 255]))
        erase_width = max(1, int(fragment_cfg.get("erase_width", 2)))
        erase_ratio = max(0.0, float(fragment_cfg.get("erase_ratio", 0.05)))
        stroke_prob = max(0.0, float(fragment_cfg.get("stroke_fragmentation_prob", 0.2)))
        closed_prob = max(0.0, float(fragment_cfg.get("closed_structure_break_prob", 0.2)))
        closed_chars = set(fragment_cfg.get("closed_structure_chars", DEFAULT_CLOSED_STRUCTURE_CHARS))
        max_stroke_fragments = max(1, int(fragment_cfg.get("max_stroke_fragments", 2)))
        max_closed_breaks = max(1, int(fragment_cfg.get("max_closed_breaks", 1)))

        glyphs = ctx.render.glyphs
        fragment_count = max(1, int(len(glyphs) * erase_ratio))
        for _ in range(fragment_count):
            glyph = ctx.py_rng.choice(glyphs)
            if ctx.py_rng.random() > stroke_prob:
                continue
            left, top, right, bottom = glyph.bbox
            if right - left < 3 or bottom - top < 3:
                continue
            for _frag in range(ctx.py_rng.randint(1, max_stroke_fragments)):
                x1 = ctx.py_rng.randint(left, max(left, right - 1))
                y1 = ctx.py_rng.randint(top, max(top, bottom - 1))
                x2 = ctx.py_rng.randint(left, max(left, right - 1))
                y2 = ctx.py_rng.randint(top, max(top, bottom - 1))
                draw.line((x1, y1, x2, y2), fill=(*bg_color, 255), width=erase_width)

        for glyph in glyphs:
            if glyph.char not in closed_chars or ctx.py_rng.random() > closed_prob:
                continue
            left, top, right, bottom = glyph.bbox
            width = max(1, right - left)
            height = max(1, bottom - top)
            for _cut in range(ctx.py_rng.randint(1, max_closed_breaks)):
                cut_w = max(1, int(width * ctx.py_rng.uniform(0.10, 0.25)))
                cut_h = max(1, int(height * ctx.py_rng.uniform(0.10, 0.25)))
                cx = left + int(width * ctx.py_rng.uniform(0.25, 0.55))
                cy = top + int(height * ctx.py_rng.uniform(0.25, 0.55))
                draw.rectangle((cx, cy, cx + cut_w, cy + cut_h), fill=(*bg_color, 255))

        ctx.image = image
        return ctx
