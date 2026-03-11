"""Image operation helpers."""

from __future__ import annotations

import string

from PIL import Image, ImageColor, ImageDraw, ImageFilter

ENG_LETTERS = string.digits + string.ascii_letters + string.punctuation


def to_color(value) -> tuple[int, int, int]:
    if isinstance(value, (tuple, list)) and len(value) == 3:
        return tuple(int(max(0, min(255, c))) for c in value)
    if isinstance(value, int):
        c = int(max(0, min(255, value)))
        return (c, c, c)
    if isinstance(value, str):
        try:
            return ImageColor.getrgb(value)
        except Exception:
            return (0, 0, 0)
    return (0, 0, 0)


def draw_rotated_char(
    image: Image.Image,
    char: str,
    font,
    anchor_xy: tuple[int, int],
    fill: tuple[int, int, int],
    angle: float,
) -> tuple[int, int, int, int]:
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox(anchor_xy, char, font=font, anchor="la", spacing=0)
    width = max(2, bbox[2] - bbox[0] + 4)
    height = max(2, bbox[3] - bbox[1] + 4)
    tile = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    tile_draw = ImageDraw.Draw(tile)
    tile_draw.text((2, 2), char, font=font, fill=(*fill, 255), anchor="la", spacing=0)
    rotated = tile.rotate(angle, expand=True, fillcolor=(255, 255, 255, 0))
    image.alpha_composite(rotated, (int(anchor_xy[0]), int(anchor_xy[1] - height * 0.8)))
    new_bbox = (anchor_xy[0], anchor_xy[1], anchor_xy[0] + rotated.size[0], anchor_xy[1] + rotated.size[1])
    return new_bbox


def add_noise_background(
    image: Image.Image,
    *,
    rng,
    density: float,
    color: tuple[int, int, int],
    min_font_size: int,
    max_font_size: int,
    font_resolver,
) -> Image.Image:
    width, height = image.size
    draw = ImageDraw.Draw(image)
    count = int(0.003 * density * width * height)
    for _ in range(max(0, count)):
        char = rng.choice(ENG_LETTERS)
        font_size = rng.randint(min_font_size, max_font_size)
        font = font_resolver(char, font_size)
        x = rng.randint(0, max(0, width - 1))
        y = rng.randint(0, max(0, height - 1))
        angle = rng.randint(0, 360)
        _ = draw_rotated_char(image, char, font, (x, y), color, angle)
    return image.filter(ImageFilter.MaxFilter(3))
