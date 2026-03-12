from __future__ import annotations

import contextlib
import logging
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

logger = logging.getLogger(__name__)

# ── Optional OCR ──
try:
    import pytesseract

    _ocr_available = True
except ImportError:
    _ocr_available = False


# ═══════════════════════════════════════════════════════════
# Payload helpers
# ═══════════════════════════════════════════════════════════

def build_visible_watermark_payload(reader_id: str, for_date) -> str:
    if hasattr(for_date, "strftime"):
        return f"{reader_id}|{for_date:%Y%m%d}"
    return f"{reader_id}|{for_date}"


_PAYLOAD_RE = re.compile(r"^([A-Za-z0-9_-]+)\|(\d{8})$")


def _parse_payload(raw: str) -> dict | None:
    """Parse 'reader_id|YYYYMMDD' from raw OCR text."""
    raw = raw.strip().replace(" ", "").replace("\n", "")
    match = _PAYLOAD_RE.search(raw)
    if match:
        return {"reader_id": match.group(1), "yyyymmdd": match.group(2)}
    # Fuzzy: try extracting from noisy OCR text
    for line in raw.split("\n"):
        line = line.strip().replace(" ", "")
        match = _PAYLOAD_RE.search(line)
        if match:
            return {"reader_id": match.group(1), "yyyymmdd": match.group(2)}
    return None


# ═══════════════════════════════════════════════════════════
# Font helpers
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# Embedding config
# ═══════════════════════════════════════════════════════════

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


def _overlay_opacity() -> int:
    """Faint alpha overlay opacity (0-255). Low values survive JPEG better."""
    return max(0, min(255, int(getattr(settings, "VISIBLE_WATERMARK_OVERLAY_OPACITY", 12))))


# ═══════════════════════════════════════════════════════════
# Text mask generation
# ═══════════════════════════════════════════════════════════

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


def _build_grayscale_text_mask(size: tuple[int, int], payload: str, device_profile: str) -> np.ndarray:
    """Build a smooth grayscale mask for the alpha overlay layer (anti-aliased)."""
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

    return np.asarray(mask_image, dtype=np.uint8)


# ═══════════════════════════════════════════════════════════
# Dual-layer embedding
# Layer 1: LSB steganography (blue/green channels)
# Layer 2: Faint alpha overlay (survives JPEG compression)
# ═══════════════════════════════════════════════════════════

def _apply_lsb_layer(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Embed watermark in LSB of blue/green channels."""
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


def _apply_alpha_overlay(image: np.ndarray, grayscale_mask: np.ndarray) -> np.ndarray:
    """Apply faint visible overlay that survives JPEG compression.

    Uses a subtle brightness reduction on watermark text regions.
    The effect is nearly invisible to the eye but creates recoverable
    patterns in the luminance channel.
    """
    opacity = _overlay_opacity()
    if opacity <= 0:
        return image

    bg_mask = _bright_background_mask(image)
    effective_mask = np.minimum(grayscale_mask, bg_mask * 255).astype(np.float32)

    # Normalize to [0, 1] then scale by opacity
    alpha = (effective_mask / 255.0) * (opacity / 255.0)

    # Darken slightly where watermark text exists
    output = image.astype(np.float32)
    for c in range(3):
        output[:, :, c] = output[:, :, c] * (1.0 - alpha * 0.35)

    return np.clip(output, 0, 255).astype(np.uint8)


def apply_visible_watermark(image: np.ndarray, payload: str, *, device_profile: str) -> np.ndarray:
    """Dual-layer visible watermark embedding.

    Layer 1: LSB steganography in blue/green channels (high precision, fragile to JPEG)
    Layer 2: Faint luminance overlay (lower precision, survives JPEG/screenshots)
    """
    if image is None:
        raise ValueError("Image is required.")

    binary_mask = _build_text_mask((image.shape[1], image.shape[0]), payload, device_profile)
    binary_mask &= _bright_background_mask(image)

    grayscale_mask = _build_grayscale_text_mask((image.shape[1], image.shape[0]), payload, device_profile)

    # Layer 1: LSB
    output = _apply_lsb_layer(image, binary_mask)

    # Layer 2: Alpha overlay
    output = _apply_alpha_overlay(output, grayscale_mask)

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
        "layers": ["lsb", "alpha_overlay"],
    }


# ═══════════════════════════════════════════════════════════
# Extraction: reveal variants
# ═══════════════════════════════════════════════════════════

def _extract_channel_bits(image: np.ndarray, channel_index: int, bit_count: int) -> np.ndarray:
    if bit_count <= 0:
        return np.zeros(image.shape[:2], dtype=np.uint8)
    low_mask = (1 << bit_count) - 1
    extracted = (image[:, :, channel_index] & low_mask).astype(np.float32)
    scale = 255.0 / max(1, low_mask)
    return np.clip(extracted * scale, 0, 255).astype(np.uint8)


def _extract_luminance_overlay(image: np.ndarray) -> np.ndarray:
    """Extract the alpha overlay layer by detecting subtle luminance patterns.

    Works even after JPEG compression by looking at local luminance variations
    that match the tiled watermark pattern.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Local mean subtraction to reveal subtle patterns
    blur = cv2.GaussianBlur(gray, (51, 51), 0)
    diff = blur - gray  # Positive where darkened (watermark overlay)

    # Normalize to [0, 255]
    diff = np.clip(diff * 8.0, 0, 255).astype(np.uint8)

    # CLAHE to enhance contrast
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(diff)

    return enhanced


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

    # ── LSB enhanced pipeline ──
    base = cv2.resize(combined, None, fx=3.2, fy=3.2, interpolation=cv2.INTER_NEAREST)
    base = cv2.GaussianBlur(base, (0, 0), sigmaX=0.8)
    base = cv2.createCLAHE(clipLimit=3.4, tileGridSize=(8, 8)).apply(base)
    boosted = cv2.convertScaleAbs(base, alpha=2.6, beta=-18)
    binary_dark = cv2.adaptiveThreshold(
        boosted, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 31, 6,
    )
    binary_light = cv2.bitwise_not(binary_dark)

    variants.append(("綜合強化", boosted))
    variants.append(("綜合黑底白字", binary_dark))
    variants.append(("綜合白底黑字", binary_light))

    # ── Alpha overlay extraction (JPEG-resistant) ──
    luminance = _extract_luminance_overlay(image)
    variants.append(("亮度疊層顯影", luminance))

    # Binarize the luminance layer
    lum_upscaled = cv2.resize(luminance, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    lum_clahe = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(8, 8)).apply(lum_upscaled)
    _, lum_binary = cv2.threshold(lum_clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("亮度疊層二值化", lum_binary))

    return variants


# ═══════════════════════════════════════════════════════════
# OCR extraction
# ═══════════════════════════════════════════════════════════

def _ocr_image(image: np.ndarray, *, lang: str = "eng") -> str:
    """Run OCR on a reveal image to extract watermark text."""
    if not _ocr_available:
        return ""
    try:
        # pytesseract expects RGB or grayscale
        if len(image.shape) == 3:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            rgb = image
        pil_img = Image.fromarray(rgb)
        text = pytesseract.image_to_string(
            pil_img,
            lang=lang,
            config="--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789|_-",
        )
        return text.strip()
    except Exception as exc:
        logger.debug("OCR failed: %s", exc)
        return ""


def _try_ocr_on_variants(
    variants: list[tuple[str, np.ndarray]],
) -> tuple[str, dict | None, str]:
    """Try OCR on each reveal variant, return first successful parse."""
    if not _ocr_available:
        return "", None, ""
    # Prioritize binary and enhanced variants for OCR
    priority_labels = ("綜合白底黑字", "綜合黑底白字", "綜合強化", "亮度疊層二值化")
    ordered = sorted(
        variants,
        key=lambda v: (0 if v[0] in priority_labels else 1, v[0]),
    )
    for label, img in ordered:
        raw = _ocr_image(img)
        if not raw:
            continue
        parsed = _parse_payload(raw)
        if parsed:
            return raw, parsed, label
    # Fallback: return best raw OCR even without successful parse
    for label, img in ordered:
        raw = _ocr_image(img)
        if raw:
            return raw, None, label
    return "", None, ""


# ═══════════════════════════════════════════════════════════
# Debug image saving
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# Main extraction pipeline
# ═══════════════════════════════════════════════════════════

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

    # Generate reveal variants
    variants = _build_reveal_variants(image)
    attempt_count = 0
    selected_method = ""
    for index, (label, reveal_image) in enumerate(variants):
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

    # Auto-OCR extraction
    ocr_raw = ""
    ocr_parsed = None
    ocr_method = ""
    if _ocr_available:
        ocr_start = time.perf_counter()
        ocr_raw, ocr_parsed, ocr_method = _try_ocr_on_variants(variants)
        ocr_ms = int((time.perf_counter() - ocr_start) * 1000)
        ocr_entry = {
            "stage": "ocr",
            "label": f"OCR ({ocr_method})" if ocr_method else "OCR",
            "success": ocr_parsed is not None,
            "duration_ms": ocr_ms,
            "message": (
                f"成功辨識：{ocr_raw[:60]}" if ocr_parsed
                else f"OCR 輸出：{ocr_raw[:60] or '(無結果)'}"
            ),
        }
        trace.append(ocr_entry)
        if progress_callback:
            progress_callback(ocr_entry)
        if ocr_method:
            selected_method = ocr_method

    duration_ms = int((time.perf_counter() - started) * 1000)
    return {
        "raw_payload": ocr_raw,
        "parsed": ocr_parsed,
        "trace": trace,
        "attempt_count": attempt_count,
        "duration_ms": duration_ms,
        "selected_method": selected_method,
        "is_valid": ocr_parsed is not None,
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
