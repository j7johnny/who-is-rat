"""Pixel-level perturb stage."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from ...font_manager import FontManager
from ...image_ops import to_color


class PerturbStage:
    """Apply edge and local pixel perturbations."""

    name = "perturb"

    def __call__(self, ctx):
        perturb_cfg = ctx.config.get("perturb", {})
        if not perturb_cfg.get("enable", True) or ctx.image is None:
            return ctx

        image = ctx.image.convert("RGBA")
        image = _apply_edge_noise(
            image=image,
            np_rng=ctx.np_rng,
            jitter_strength=float(perturb_cfg.get("edge_jitter_strength", 0.0)),
            brightness_noise=float(perturb_cfg.get("edge_brightness_noise", 0.0)),
        )
        image = _apply_local_contrast_noise(
            image=image,
            py_rng=ctx.py_rng,
            noise_strength=float(perturb_cfg.get("local_contrast_noise", 0.0)),
            patch_count=int(perturb_cfg.get("local_contrast_patches", 0)),
        )
        if perturb_cfg.get("adversarial_watermark_enable", True):
            font_cfg = ctx.config.get("font", {})
            font_manager = FontManager(
                paths=font_cfg.get("paths", []),
                directories=font_cfg.get("directories", []),
                fallback_to_default=True,
            )
            image = _apply_watermark(
                image=image,
                py_rng=ctx.py_rng,
                font_manager=font_manager,
                text=str(perturb_cfg.get("watermark_text", "anti7ocr")),
                opacity=int(perturb_cfg.get("watermark_opacity", 18)),
                density=float(perturb_cfg.get("watermark_density", 0.10)),
                scale=float(perturb_cfg.get("watermark_scale", 0.5)),
            )
        ctx.image = image
        return ctx


def _apply_edge_noise(image: Image.Image, np_rng, jitter_strength: float, brightness_noise: float) -> Image.Image:
    rgba = np.array(image).astype(np.float32)
    gray = np.array(image.convert("L").filter(ImageFilter.FIND_EDGES))
    mask = gray > np.percentile(gray, 70)
    if jitter_strength > 0:
        shift_x = int(np.clip(np_rng.normal(0, 2.0 * jitter_strength * 10), -3, 3))
        shift_y = int(np.clip(np_rng.normal(0, 2.0 * jitter_strength * 10), -3, 3))
        rolled = np.roll(rgba[:, :, :3], shift=(shift_y, shift_x), axis=(0, 1))
        blend_ratio = min(0.35, max(0.05, jitter_strength * 2.0))
        rgba[:, :, :3][mask] = (
            (1.0 - blend_ratio) * rgba[:, :, :3][mask] + blend_ratio * rolled[mask]
        )
        jitter = np_rng.normal(0, 255.0 * jitter_strength, size=rgba[:, :, :3].shape)
        rgba[:, :, :3][mask] += jitter[mask]
    if brightness_noise > 0:
        brighten = np_rng.uniform(-brightness_noise, brightness_noise, size=rgba[:, :, :3].shape)
        rgba[:, :, :3][mask] += brighten[mask]
    rgba[:, :, :3] = np.clip(rgba[:, :, :3], 0, 255)
    return Image.fromarray(rgba.astype(np.uint8), mode="RGBA")


def _apply_local_contrast_noise(image: Image.Image, py_rng, noise_strength: float, patch_count: int) -> Image.Image:
    if noise_strength <= 0 or patch_count <= 0:
        return image
    out = image.copy()
    width, height = out.size
    for _ in range(patch_count):
        patch_w = max(8, int(width * py_rng.uniform(0.04, 0.14)))
        patch_h = max(8, int(height * py_rng.uniform(0.03, 0.10)))
        left = py_rng.randint(0, max(0, width - patch_w))
        top = py_rng.randint(0, max(0, height - patch_h))
        box = (left, top, left + patch_w, top + patch_h)
        crop = out.crop(box)
        factor = 1.0 + py_rng.uniform(-noise_strength, noise_strength)
        crop = ImageEnhance.Contrast(crop).enhance(max(0.2, factor))
        out.paste(crop, box)
    return out


def _apply_watermark(
    *,
    image: Image.Image,
    py_rng,
    font_manager: FontManager,
    text: str,
    opacity: int,
    density: float,
    scale: float,
) -> Image.Image:
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    color = (*to_color([40, 40, 40]), max(0, min(255, opacity)))
    step = max(16, int(math.sqrt(width * height) * max(0.04, density)))
    font_size = max(10, int(min(width, height) * max(0.02, scale * 0.05)))
    font = font_manager.get_font(text[0], font_size)

    offset_x = py_rng.randint(0, step)
    offset_y = py_rng.randint(0, step)
    for y in range(-step + offset_y, height + step, step):
        for x in range(-step + offset_x, width + step, step):
            draw.text((x, y), text, fill=color, font=font)
    rotation = py_rng.uniform(-6.0, 6.0)
    rotated_overlay = overlay.rotate(rotation, expand=False)
    return Image.alpha_composite(image, rotated_overlay)
