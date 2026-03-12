"""Render stage."""

from __future__ import annotations

from PIL import Image, ImageDraw

from ...font_manager import FontManager
from ...image_ops import add_noise_background, draw_rotated_char, to_color
from ...models import GlyphRenderMeta, RenderResult

# Punctuation characters that should be rotated 90 degrees clockwise
# when rendered in vertical text layout.
_VERTICAL_ROTATE_PUNCTUATION = set(
    "\uff08\uff09"   # （）fullwidth parentheses
    "\u3010\u3011"   # 【】
    "\u300c\u300d"   # 「」
    "\u300e\u300f"   # 『』
    "\u2014"         # — em dash
    "\uff5e"         # ～ fullwidth tilde
    "\u2026"         # … ellipsis
    "\u3001"         # 、 ideographic comma
)


class RenderStage:
    """Render glyph tokens into an image."""

    name = "render"

    def __call__(self, ctx):
        if ctx.layout is None:
            raise RuntimeError("Layout result is required before render stage")

        layout_cfg = ctx.config["layout"]
        direction = str(layout_cfg.get("direction", "horizontal"))

        if direction == "vertical":
            return self._render_vertical(ctx)
        return self._render_horizontal(ctx)

    # ------------------------------------------------------------------
    # Horizontal rendering (original behaviour, untouched)
    # ------------------------------------------------------------------

    def _render_horizontal(self, ctx):
        canvas_cfg = ctx.config["canvas"]
        font_cfg = ctx.config["font"]
        layout_cfg = ctx.config["layout"]
        text_cfg = ctx.config["text"]
        bg_cfg = ctx.config["background"]

        supersample = max(1, int(canvas_cfg.get("supersample", 1)))
        width = int(canvas_cfg["width"]) * supersample
        height = int(canvas_cfg["height"]) * supersample
        margin = int(canvas_cfg["margin"]) * supersample
        min_size = max(8, int(font_cfg.get("min_size", 24)) * supersample)
        max_size = max(min_size + 1, int(font_cfg.get("max_size", min_size + 1)) * supersample)
        line_height_base = max_size * float(layout_cfg.get("line_height_multiplier", 1.2))
        text_color = to_color(canvas_cfg.get("text_color", [0, 0, 0]))
        background_color = to_color(canvas_cfg.get("background_color", [255, 255, 255]))

        bg_image = ctx.metadata.get("background_image")
        if bg_image is not None:
            image = bg_image.convert("RGBA").resize((width, height))
        else:
            image = Image.new("RGBA", (width, height), (*background_color, 255))
        font_manager = FontManager(
            paths=font_cfg.get("paths", []),
            directories=font_cfg.get("directories", []),
            fallback_to_default=bool(font_cfg.get("fallback_to_default", True)),
        )

        if bg_cfg.get("enable", True):
            add_noise_background(
                image,
                rng=ctx.py_rng,
                density=float(bg_cfg.get("density", 0.10)),
                color=to_color(bg_cfg.get("foreground", [120, 120, 120])),
                min_font_size=max(8, int(bg_cfg.get("min_font_size", 10)) * supersample),
                max_font_size=max(9, int(bg_cfg.get("max_font_size", 20)) * supersample),
                font_resolver=font_manager.get_font,
            )

        draw = ImageDraw.Draw(image)
        glyphs: list[GlyphRenderMeta] = []
        line_index = 0
        x = margin
        y = margin + int(max_size * 0.9)

        for token in ctx.layout.tokens:
            if token.line_index != line_index:
                line_index = token.line_index
                x = margin
                y = margin + int(line_height_base * line_index + max_size * 0.9)

            jittered_size = int(ctx.py_rng.randint(min_size, max_size) * (1.0 + token.scale_jitter))
            font_size = max(8, jittered_size)
            y_with_jitter = int(y + token.baseline_jitter * supersample)
            font = font_manager.get_font(token.char, font_size)

            probe_box = draw.textbbox((x, y_with_jitter), token.char, font=font, anchor="la", spacing=0)
            glyph_w = max(1, probe_box[2] - probe_box[0])
            if probe_box[2] >= width - margin:
                line_index += 1
                token.line_index = line_index
                x = margin
                y = margin + int(line_height_base * line_index + max_size * 0.9)
                y_with_jitter = int(y + token.baseline_jitter * supersample)
                probe_box = draw.textbbox((x, y_with_jitter), token.char, font=font, anchor="la", spacing=0)
                glyph_w = max(1, probe_box[2] - probe_box[0])

            while probe_box[3] >= image.size[1] - margin:
                image = _expand_canvas(image, background_color)
                draw = ImageDraw.Draw(image)
                probe_box = draw.textbbox((x, y_with_jitter), token.char, font=font, anchor="la", spacing=0)

            if token.reverse:
                bbox = draw_rotated_char(
                    image,
                    token.char,
                    font,
                    (x, y_with_jitter),
                    text_color,
                    angle=token.rotation or ctx.py_rng.randint(
                        int(text_cfg.get("reverse_rotation_range", [170, 190])[0]),
                        int(text_cfg.get("reverse_rotation_range", [170, 190])[1]),
                    ),
                )
            else:
                draw.text((x, y_with_jitter), token.char, font=font, fill=(*text_color, 255), anchor="la", spacing=0)
                bbox = draw.textbbox((x, y_with_jitter), token.char, font=font, anchor="la", spacing=0)

            glyphs.append(
                GlyphRenderMeta(
                    char=token.char,
                    bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                    line_index=token.line_index,
                    font_size=int(font_size / supersample),
                    reverse=token.reverse,
                )
            )
            x = int(x + glyph_w + token.kerning_jitter * supersample)
            x = max(margin, x)

        if supersample > 1:
            image = image.resize((int(canvas_cfg["width"]), int(canvas_cfg["height"])), resample=Image.Resampling.LANCZOS)
            glyphs = _scale_glyph_boxes(glyphs, supersample)
        ctx.render = RenderResult(image=image, glyphs=glyphs)
        ctx.image = image
        return ctx

    # ------------------------------------------------------------------
    # Vertical rendering  (top-to-bottom, right-to-left columns)
    # ------------------------------------------------------------------

    def _render_vertical(self, ctx):
        canvas_cfg = ctx.config["canvas"]
        font_cfg = ctx.config["font"]
        layout_cfg = ctx.config["layout"]
        text_cfg = ctx.config["text"]
        bg_cfg = ctx.config["background"]

        supersample = max(1, int(canvas_cfg.get("supersample", 1)))
        margin = int(canvas_cfg["margin"]) * supersample
        min_size = max(8, int(font_cfg.get("min_size", 24)) * supersample)
        max_size = max(min_size + 1, int(font_cfg.get("max_size", min_size + 1)) * supersample)
        line_height_mult = float(layout_cfg.get("line_height_multiplier", 1.2))
        text_color = to_color(canvas_cfg.get("text_color", [0, 0, 0]))
        background_color = to_color(canvas_cfg.get("background_color", [255, 255, 255]))
        max_chars_per_column = int(layout_cfg.get("max_chars_per_column", 20))

        # Column width is based on the maximum font size with the line-height
        # multiplier applied (mirrors line_height_base in horizontal mode).
        column_width = int(max_size * line_height_mult)
        # Character height step for vertical stacking.
        char_height_step = int(max_size * line_height_mult)

        # Determine the number of columns from the tokens.
        num_columns = 0
        if ctx.layout.tokens:
            num_columns = max(t.line_index for t in ctx.layout.tokens) + 1

        # Canvas dimensions:
        #   width  = margin * 2 + num_columns * column_width
        #   height = margin * 2 + max_chars_per_column * char_height_step
        canvas_width = max(
            int(canvas_cfg["width"]) * supersample,
            margin * 2 + num_columns * column_width,
        )
        canvas_height = max(
            int(canvas_cfg["height"]) * supersample,
            margin * 2 + max_chars_per_column * char_height_step,
        )

        bg_image = ctx.metadata.get("background_image")
        if bg_image is not None:
            image = bg_image.convert("RGBA").resize((canvas_width, canvas_height))
        else:
            image = Image.new("RGBA", (canvas_width, canvas_height), (*background_color, 255))

        font_manager = FontManager(
            paths=font_cfg.get("paths", []),
            directories=font_cfg.get("directories", []),
            fallback_to_default=bool(font_cfg.get("fallback_to_default", True)),
        )

        if bg_cfg.get("enable", True):
            add_noise_background(
                image,
                rng=ctx.py_rng,
                density=float(bg_cfg.get("density", 0.10)),
                color=to_color(bg_cfg.get("foreground", [120, 120, 120])),
                min_font_size=max(8, int(bg_cfg.get("min_font_size", 10)) * supersample),
                max_font_size=max(9, int(bg_cfg.get("max_font_size", 20)) * supersample),
                font_resolver=font_manager.get_font,
            )

        draw = ImageDraw.Draw(image)
        glyphs: list[GlyphRenderMeta] = []

        for token in ctx.layout.tokens:
            column_index = token.line_index
            char_index = token.char_index

            jittered_size = int(
                ctx.py_rng.randint(min_size, max_size) * (1.0 + token.scale_jitter)
            )
            font_size = max(8, jittered_size)
            font = font_manager.get_font(token.char, font_size)

            # X position: columns flow right-to-left.
            # column 0 is the rightmost column.
            base_x = canvas_width - (column_index + 1) * column_width + margin
            # Y position: characters stack top-to-bottom.
            base_y = margin + char_index * char_height_step + int(max_size * 0.9)

            # Jitter application for vertical mode:
            #   baseline_jitter  -> horizontal offset (left/right)
            #   kerning_jitter   -> vertical offset (up/down spacing)
            x = int(base_x + token.baseline_jitter * supersample)
            y = int(base_y + token.kerning_jitter * supersample)

            # Expand canvas vertically if character falls outside bounds.
            probe_box = draw.textbbox((x, y), token.char, font=font, anchor="la", spacing=0)
            while probe_box[3] >= image.size[1] - margin:
                image = _expand_canvas(image, background_color)
                draw = ImageDraw.Draw(image)
                probe_box = draw.textbbox((x, y), token.char, font=font, anchor="la", spacing=0)

            # Check if this punctuation should be rotated for vertical display.
            needs_vertical_rotation = token.char in _VERTICAL_ROTATE_PUNCTUATION

            if token.reverse:
                bbox = draw_rotated_char(
                    image,
                    token.char,
                    font,
                    (x, y),
                    text_color,
                    angle=token.rotation or ctx.py_rng.randint(
                        int(text_cfg.get("reverse_rotation_range", [170, 190])[0]),
                        int(text_cfg.get("reverse_rotation_range", [170, 190])[1]),
                    ),
                )
            elif needs_vertical_rotation:
                bbox = _draw_vertical_punctuation(image, token.char, font, (x, y), text_color)
            else:
                draw.text(
                    (x, y), token.char, font=font,
                    fill=(*text_color, 255), anchor="la", spacing=0,
                )
                bbox = draw.textbbox((x, y), token.char, font=font, anchor="la", spacing=0)

            glyphs.append(
                GlyphRenderMeta(
                    char=token.char,
                    bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                    line_index=token.line_index,
                    font_size=int(font_size / supersample),
                    reverse=token.reverse,
                )
            )

        if supersample > 1:
            final_w = max(
                int(canvas_cfg["width"]),
                int(canvas_width / supersample),
            )
            final_h = max(
                int(canvas_cfg["height"]),
                int(canvas_height / supersample),
            )
            image = image.resize((final_w, final_h), resample=Image.Resampling.LANCZOS)
            glyphs = _scale_glyph_boxes(glyphs, supersample)

        ctx.render = RenderResult(image=image, glyphs=glyphs)
        ctx.image = image
        return ctx


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _draw_vertical_punctuation(
    image: Image.Image,
    char: str,
    font,
    anchor_xy: tuple[int, int],
    fill: tuple[int, int, int],
) -> tuple[int, int, int, int]:
    """Render a punctuation character rotated 90 degrees clockwise for vertical text."""
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox(anchor_xy, char, font=font, anchor="la", spacing=0)
    width = max(2, bbox[2] - bbox[0] + 4)
    height = max(2, bbox[3] - bbox[1] + 4)
    tile = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    tile_draw = ImageDraw.Draw(tile)
    tile_draw.text((2, 2), char, font=font, fill=(*fill, 255), anchor="la", spacing=0)
    # Rotate 90 degrees clockwise (PIL uses counter-clockwise, so -90 = 270).
    rotated = tile.rotate(-90, expand=True, fillcolor=(255, 255, 255, 0))
    # Centre the rotated glyph around the original anchor position.
    paste_x = int(anchor_xy[0] + (width - rotated.size[0]) / 2)
    paste_y = int(anchor_xy[1] - height * 0.8 + (height - rotated.size[1]) / 2)
    image.alpha_composite(rotated, (max(0, paste_x), max(0, paste_y)))
    new_bbox = (
        paste_x,
        paste_y,
        paste_x + rotated.size[0],
        paste_y + rotated.size[1],
    )
    return new_bbox


def _expand_canvas(image: Image.Image, bg_color: tuple[int, int, int]) -> Image.Image:
    width, height = image.size
    expanded = Image.new("RGBA", (width, height * 2), (*bg_color, 255))
    expanded.paste(image, (0, 0))
    return expanded


def _scale_glyph_boxes(glyphs: list[GlyphRenderMeta], supersample: int) -> list[GlyphRenderMeta]:
    scaled: list[GlyphRenderMeta] = []
    for item in glyphs:
        left, top, right, bottom = item.bbox
        scaled.append(
            GlyphRenderMeta(
                char=item.char,
                bbox=(
                    int(left / supersample),
                    int(top / supersample),
                    int(right / supersample),
                    int(bottom / supersample),
                ),
                line_index=item.line_index,
                font_size=item.font_size,
                reverse=item.reverse,
            )
        )
    return scaled
