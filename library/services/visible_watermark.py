from __future__ import annotations

import contextlib
import re
import time
from typing import Callable
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

from .font_library import list_runtime_font_paths
from .storage import ensure_parent, media_relative
from .watermark import ExtractionStopped


def build_visible_watermark_payload(reader_id: str, for_date) -> str:
    if hasattr(for_date, "strftime"):
        return f"{reader_id}|{for_date:%Y%m%d}"
    return f"{reader_id}|{for_date}"


def _runtime_font_paths() -> list[str]:
    preferred = [str(path) for path in settings.ANTI_OCR_FONT_PATHS if path and Path(path).is_file()]
    runtime = list_runtime_font_paths()
    seen: set[str] = set()
    ordered: list[str] = []
    for font_path in preferred + runtime:
        normalized = str(Path(font_path))
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _default_font(size: int):
    with contextlib.suppress(TypeError):
        return ImageFont.load_default(size=max(8, size))
    return ImageFont.load_default()


def _measure_text(payload: str, font) -> tuple[int, int]:
    probe = Image.new("L", (8, 8), 0)
    draw = ImageDraw.Draw(probe)
    left, top, right, bottom = draw.textbbox((0, 0), payload, font=font)
    return max(1, right - left), max(1, bottom - top)


def _load_font(payload: str, *, device_profile: str):
    size = _font_size(device_profile)
    for font_path in _runtime_font_paths():
        try:
            font = ImageFont.truetype(font_path, size=size)
            text_width, text_height = _measure_text(payload, font)
        except Exception:
            continue
        return font, text_width, text_height

    fallback_font = _default_font(size)
    text_width, text_height = _measure_text(payload, fallback_font)
    return fallback_font, text_width, text_height


def _font_size(device_profile: str) -> int:
    return (
        settings.VISIBLE_WATERMARK_DESKTOP_FONT_SIZE
        if device_profile == "desktop"
        else settings.VISIBLE_WATERMARK_MOBILE_FONT_SIZE
    )


def _row_spacing(device_profile: str) -> int:
    return (
        settings.VISIBLE_WATERMARK_DESKTOP_ROW_SPACING
        if device_profile == "desktop"
        else settings.VISIBLE_WATERMARK_MOBILE_ROW_SPACING
    )


def _text_metrics(payload: str, device_profile: str) -> tuple[ImageFont.FreeTypeFont, int, int]:
    font, text_width, text_height = _load_font(payload, device_profile=device_profile)
    return font, text_width, text_height


def _bright_background_mask(image: np.ndarray) -> np.ndarray:
    threshold = int(getattr(settings, "VISIBLE_WATERMARK_BACKGROUND_THRESHOLD", 145))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return (gray >= threshold).astype(np.uint8)


def _rotation_angle() -> int:
    return int(getattr(settings, "VISIBLE_WATERMARK_ROTATION", 28))


def _blue_bits() -> int:
    return max(0, int(getattr(settings, "VISIBLE_WATERMARK_BLUE_BITS", 2)))


def _green_bits() -> int:
    return max(0, int(getattr(settings, "VISIBLE_WATERMARK_GREEN_BITS", 1)))


def _build_text_mask(size: tuple[int, int], payload: str, device_profile: str) -> np.ndarray:
    width, height = size
    font, text_width, text_height = _text_metrics(payload, device_profile)
    spacing_x = max(text_width + settings.VISIBLE_WATERMARK_TEXT_GAP, int(text_width * 1.55))
    spacing_y = max(text_height + _row_spacing(device_profile), int(text_height * 2.4))

    tile = Image.new("L", (text_width + 80, text_height + 60), 0)
    tile_draw = ImageDraw.Draw(tile)
    tile_draw.text((24, 18), payload, fill=255, font=font)
    rotated = tile.rotate(_rotation_angle(), expand=True, fillcolor=0)

    mask_image = Image.new("L", size, 0)
    for row_index, y in enumerate(range(-rotated.height, height + rotated.height, spacing_y)):
        x_offset = 0 if row_index % 2 == 0 else spacing_x // 2
        for x in range(-rotated.width, width + rotated.width, spacing_x):
            mask_image.paste(rotated, (x - x_offset, y), rotated)

    mask = (np.asarray(mask_image, dtype=np.uint8) > 127).astype(np.uint8)
    return mask


def apply_visible_watermark(image: np.ndarray, payload: str, *, device_profile: str) -> np.ndarray:
    if image is None:
        raise ValueError("Image is required.")

    mask = _build_text_mask((image.shape[1], image.shape[0]), payload, device_profile)
    mask &= _bright_background_mask(image)

    output = image.copy()
    channel_plan = (
        (2, _blue_bits()),
        (1, _green_bits()),
    )
    for channel_index, bits in channel_plan:
        if bits <= 0:
            continue
        low_mask = (1 << bits) - 1
        keep_mask = np.uint8(0xFF ^ low_mask)
        channel = output[:, :, channel_index]
        embedded = (channel & keep_mask) | (mask * low_mask).astype(np.uint8)
        output[:, :, channel_index] = np.where(mask > 0, embedded, channel)
    return output


def embed_visible_watermark(
    input_path: str,
    output_path: str,
    payload: str,
    *,
    device_profile: str,
) -> dict:
    image = cv2.imread(input_path, flags=cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Unable to read input image: {input_path}")

    watermarked = apply_visible_watermark(image, payload, device_profile=device_profile)
    if not cv2.imwrite(output_path, watermarked):
        raise RuntimeError(f"Unable to write visible watermark image: {output_path}")

    return {
        "payload": payload,
        "width": int(watermarked.shape[1]),
        "height": int(watermarked.shape[0]),
        "device_profile": device_profile,
    }


def _extract_channel_bits(image: np.ndarray, channel_index: int, bit_count: int) -> np.ndarray:
    if bit_count <= 0:
        return np.zeros(image.shape[:2], dtype=np.uint8)
    low_mask = (1 << bit_count) - 1
    extracted = (image[:, :, channel_index] & low_mask).astype(np.float32)
    scale = 255.0 / max(1, low_mask)
    return np.clip(extracted * scale, 0, 255).astype(np.uint8)


def _build_reveal_variants(image: np.ndarray):
    blue = _extract_channel_bits(image, 2, _blue_bits())
    green = _extract_channel_bits(image, 1, _green_bits())
    combined = np.maximum(blue, green)

    variants: list[tuple[str, np.ndarray]] = [
        ("綜合顯影", combined),
    ]
    if _blue_bits() > 0:
        variants.append(("藍通道顯影", blue))
    if _green_bits() > 0:
        variants.append(("綠通道顯影", green))

    base = cv2.resize(combined, None, fx=3.2, fy=3.2, interpolation=cv2.INTER_NEAREST)
    base = cv2.GaussianBlur(base, (0, 0), sigmaX=0.8)
    base = cv2.createCLAHE(clipLimit=3.4, tileGridSize=(8, 8)).apply(base)
    boosted = cv2.convertScaleAbs(base, alpha=2.6, beta=-18)
    binary_dark = cv2.adaptiveThreshold(
        boosted,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        6,
    )
    binary_light = cv2.bitwise_not(binary_dark)

    variants.append(("綜合強化", boosted))
    variants.append(("綜合黑底白字", binary_dark))
    variants.append(("綜合白底黑字", binary_light))
    return variants


def _save_debug_image(debug_prefix: str | None, label: str, image: np.ndarray, index: int) -> tuple[str | None, str | None]:
    if not debug_prefix:
        return None, None
    safe_label = re.sub(r"[^A-Za-z0-9]+", "-", label.lower()).strip("-") or "preview"
    relative_path = media_relative(
        "visible_watermark_debug",
        debug_prefix,
        f"{index:03d}-{safe_label}.png",
    )
    absolute_path = ensure_parent(relative_path)
    cv2.imwrite(str(absolute_path), image)
    return relative_path, f"{settings.MEDIA_URL}{relative_path}"


def extract_visible_watermark_from_bytes(
    file_bytes: bytes,
    *,
    progress_callback: Callable[[dict], None] | None = None,
    debug_prefix: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    image = cv2.imdecode(np.frombuffer(file_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return {
            "raw_payload": "",
            "parsed": None,
            "trace": [
                {
                    "stage": "input",
                    "label": "decode image",
                    "success": False,
                    "duration_ms": 0,
                    "message": "Unable to decode uploaded image.",
                }
            ],
            "attempt_count": 0,
            "duration_ms": 0,
            "selected_method": "",
            "is_valid": False,
            "image_width": 0,
            "image_height": 0,
        }

    started = time.perf_counter()
    trace = [
        {
            "stage": "input",
            "label": "decode image",
            "success": True,
            "duration_ms": 0,
            "message": f"Loaded image {image.shape[1]}x{image.shape[0]}",
        }
    ]
    if progress_callback:
        progress_callback(trace[0])

    attempt_count = 0
    selected_method = ""
    for index, (label, reveal_image) in enumerate(_build_reveal_variants(image)):
        if should_stop and should_stop():
            raise ExtractionStopped("Visible extraction canceled by user.")
        preview_relative_path, preview_url = _save_debug_image(debug_prefix, label, reveal_image, index)
        attempt_count += 1
        if not selected_method:
            selected_method = label
        entry = {
            "stage": "reveal",
            "label": label,
            "success": True,
            "duration_ms": 0,
            "message": "Generated visible watermark reveal image.",
        }
        if preview_url:
            entry["preview_url"] = preview_url
        if preview_relative_path:
            entry["preview_relative_path"] = preview_relative_path
        trace.append(entry)
        if progress_callback:
            progress_callback(entry)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return {
        "raw_payload": "",
        "parsed": None,
        "trace": trace,
        "attempt_count": attempt_count,
        "duration_ms": duration_ms,
        "selected_method": selected_method,
        "is_valid": attempt_count > 0,
        "image_width": int(image.shape[1]),
        "image_height": int(image.shape[0]),
    }


def extract_visible_watermark_from_path(
    image_path: str,
    *,
    progress_callback: Callable[[dict], None] | None = None,
    debug_prefix: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    with open(image_path, "rb") as image_file:
        return extract_visible_watermark_from_bytes(
            image_file.read(),
            progress_callback=progress_callback,
            debug_prefix=debug_prefix,
            should_stop=should_stop,
        )
