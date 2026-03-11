"""Render stage."""

from __future__ import annotations

from PIL import Image, ImageDraw

from ...font_manager import FontManager
from ...image_ops import add_noise_background, draw_rotated_char, to_color
from ...models import GlyphRenderMeta, RenderResult


class RenderStage:
    """Render glyph tokens into an image."""

    name = "render"

    def __call__(self, ctx):
        if ctx.layout is None:
            raise RuntimeError("Layout result is required before render stage")

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
