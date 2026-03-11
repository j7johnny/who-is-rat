from __future__ import annotations

from collections import Counter, defaultdict
import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import random
import re
import time
from typing import Callable

import cv2
import numpy as np
from blind_watermark import WaterMark
from django.conf import settings
from django.utils import timezone

from accounts.models import User
from library.models import DailyPageCache

watermark_pattern = re.compile(r"(?P<reader_id>[A-Za-z0-9_.-]{1,16})\|(?P<yyyymmdd>\d{8})")
bit_redundancy = 4
carrier_seed = 20260308
crop_sampler_seed = 20260308
max_crop_attempts = 260
source_match_recent_days = 7
source_match_max_recent_pages = 240
source_match_probe_limit = 24
source_match_top_hits = 6
source_match_min_score = 0.66
source_match_metadata_score = 0.975
source_match_short_circuit_score = 0.995

watermark_embed_profiles = (
    {"name": "direct", "seed": carrier_seed, "noise_strength": 0, "grid_strength": 0},
)


@dataclass(frozen=True)
class SourceProbe:
    label: str
    color_image: np.ndarray
    gray_image: np.ndarray


@dataclass(frozen=True)
class TemplateMatchHit:
    x: int
    y: int
    score: float
    scale: float
    probe_width: int
    probe_height: int


@dataclass(frozen=True)
class SourceMatchCandidate:
    label: str
    reader_id: str
    yyyymmdd: str
    gray_image: np.ndarray
    canvas_shape: tuple[int, int]


class ExtractionStopped(RuntimeError):
    """Raised when extraction is canceled by user request."""


def build_watermark_payload(reader_id: str, for_date) -> str:
    payload = f"{reader_id}|{for_date:%Y%m%d}"
    fixed_length = settings.WATERMARK_FIXED_LENGTH
    if len(payload) > fixed_length:
        raise ValueError("Watermark payload exceeds the configured fixed length.")
    return payload.ljust(fixed_length, "~")


def sanitize_raw_payload(raw: str) -> str:
    sanitized = "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in raw)
    fixed_length = settings.WATERMARK_FIXED_LENGTH
    return sanitized[:fixed_length].ljust(fixed_length, "~")


def parse_watermark_payload(payload: str) -> dict | None:
    normalized = payload.replace("\x00", "").rstrip("~")
    matches = list(watermark_pattern.finditer(normalized))
    if not matches:
        return None
    match = max(matches, key=lambda item: (len(item.group("reader_id")), -item.start()))
    return {
        "reader_id": match.group("reader_id"),
        "yyyymmdd": match.group("yyyymmdd"),
        "raw": match.group(0),
    }


def get_watermark_client() -> WaterMark:
    return WaterMark(
        password_wm=settings.WATERMARK_PASSWORD_WM,
        password_img=settings.WATERMARK_PASSWORD_IMG,
    )


def payload_to_bits(payload: str) -> np.ndarray:
    raw_bits = "".join(f"{byte:08b}" for byte in payload.encode("ascii"))
    bit_array = np.array([bit == "1" for bit in raw_bits], dtype=bool)
    return np.repeat(bit_array, bit_redundancy)


def bits_to_payload(bit_values) -> str:
    normalized_bits: list[str] = []
    for start in range(0, len(bit_values), bit_redundancy):
        chunk = np.asarray(bit_values[start : start + bit_redundancy]).astype(float)
        normalized_bits.append("1" if chunk.mean() >= 0.5 else "0")

    bytes_out = bytearray()
    for start in range(0, len(normalized_bits), 8):
        byte_bits = normalized_bits[start : start + 8]
        if len(byte_bits) == 8:
            bytes_out.append(int("".join(byte_bits), 2))
    return bytes(bytes_out).decode("ascii", errors="replace")


def build_carrier_image(
    input_path: str,
    *,
    seed: int = carrier_seed,
    noise_strength: int = 0,
    grid_strength: int = 0,
) -> np.ndarray:
    image = cv2.imread(input_path, flags=cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Unable to read carrier image: {input_path}")
    if noise_strength <= 0 and grid_strength <= 0:
        return image

    rng = np.random.default_rng(seed)
    noise = rng.integers(-noise_strength, noise_strength + 1, size=image.shape, dtype=np.int16)
    textured = np.clip(image.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    if grid_strength > 0:
        textured[::12, :, :] = np.clip(textured[::12, :, :].astype(np.int16) + grid_strength, 0, 255).astype(
            np.uint8
        )
        textured[:, ::12, :] = np.clip(textured[:, ::12, :].astype(np.int16) - grid_strength, 0, 255).astype(
            np.uint8
        )
    return textured


def minimum_carrier_height(width: int) -> int:
    if width <= 420:
        return 220
    return 180


def pad_carrier_image(image: np.ndarray, extra_height: int = 0) -> np.ndarray:
    target_height = max(image.shape[0], minimum_carrier_height(image.shape[1]) + extra_height)
    if image.shape[0] >= target_height:
        return image

    fill_height = target_height - image.shape[0]
    tail_height = min(8, image.shape[0]) or 1
    tail_strip = image[image.shape[0] - tail_height :, :, :]
    filler = cv2.resize(tail_strip, (image.shape[1], fill_height), interpolation=cv2.INTER_LINEAR)
    return np.vstack([image, filler])


def resize_candidate(image: np.ndarray, target_width: int) -> np.ndarray:
    if image.shape[1] == target_width:
        return image
    target_height = max(int(image.shape[0] * target_width / image.shape[1]), minimum_carrier_height(target_width))
    return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_LINEAR)


def try_extract_payload(image: np.ndarray) -> tuple[str, dict | None]:
    watermark = get_watermark_client()
    extracted_bits = watermark.extract(
        embed_img=image,
        wm_shape=settings.WATERMARK_FIXED_LENGTH * 8 * bit_redundancy,
        mode="bit",
    )
    extracted = bits_to_payload(extracted_bits)
    return extracted, parse_watermark_payload(extracted)


def build_recovery_context(
    expected_reader_ids: list[str] | None = None,
    expected_dates: list[str] | None = None,
) -> dict:
    today = timezone.localdate()
    recent_dates = [(today - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(60)]
    context = {
        "expected_reader_ids": [item.lower() for item in (expected_reader_ids or []) if item],
        "expected_dates": [item for item in (expected_dates or []) if item],
        "reader_ids": [],
        "global_dates": [],
        "reader_date_cache": {},
    }
    if context["expected_reader_ids"]:
        context["reader_ids"] = context["expected_reader_ids"]
    else:
        context["reader_ids"] = list(
            User.objects.filter(role=User.Role.READER, is_active=True).values_list("username", flat=True)
        )

    if context["expected_dates"]:
        context["global_dates"] = list(dict.fromkeys(context["expected_dates"] + recent_dates))
    else:
        cached_dates = list(
            DailyPageCache.objects.filter(for_date__lte=today)
            .order_by("-for_date")
            .values_list("for_date", flat=True)
            .distinct()
        )
        formatted_dates = [item.strftime("%Y%m%d") for item in cached_dates]
        context["global_dates"] = list(dict.fromkeys(formatted_dates + recent_dates))
    return context


def get_known_dates_for_reader(context: dict, reader_id: str | None = None) -> list[str]:
    if context["expected_dates"]:
        return context["expected_dates"]
    if not reader_id:
        return context["global_dates"]
    if reader_id not in context["reader_date_cache"]:
        today = timezone.localdate()
        cached_dates = list(
            DailyPageCache.objects.filter(reader__username=reader_id, for_date__lte=today)
            .order_by("-for_date")
            .values_list("for_date", flat=True)
            .distinct()
        )
        formatted_dates = [item.strftime("%Y%m%d") for item in cached_dates]
        context["reader_date_cache"][reader_id] = formatted_dates or context["global_dates"]
    return context["reader_date_cache"][reader_id]


def valid_yyyymmdd(candidate: str) -> bool:
    if not candidate.isdigit() or len(candidate) != 8:
        return False
    with contextlib.suppress(ValueError):
        datetime.strptime(candidate, "%Y%m%d")
        return True
    return False


def resolve_reader_id(candidate: str, context: dict) -> str:
    reader_ids = context["reader_ids"]
    if not reader_ids:
        return candidate
    lower_candidate = candidate.lower()
    if lower_candidate in reader_ids:
        return lower_candidate
    if len(reader_ids) == 1:
        only_reader = reader_ids[0]
        if lower_candidate and (
            lower_candidate in only_reader
            or only_reader.endswith(lower_candidate)
            or SequenceMatcher(None, lower_candidate, only_reader).ratio() >= 0.45
        ):
            return only_reader
    scored = sorted(
        ((SequenceMatcher(None, lower_candidate, reader_id).ratio(), reader_id) for reader_id in reader_ids),
        reverse=True,
    )
    best_score, best_match = scored[0]
    if best_score < 0.62:
        return candidate
    if len(scored) > 1 and best_score - scored[1][0] < 0.08 and not context["expected_reader_ids"]:
        return candidate
    return best_match


def resolve_reader_from_raw(raw: str, context: dict) -> tuple[str | None, int]:
    reader_ids = context["reader_ids"]
    if not reader_ids:
        return None, 0

    sanitized = sanitize_raw_payload(raw).lower()
    best = None
    second = None
    for reader_id in reader_ids:
        for offset in range(0, 3):
            fragment = sanitized[offset : offset + len(reader_id)]
            score = SequenceMatcher(None, fragment, reader_id).ratio()
            candidate = (score, -offset, reader_id)
            if best is None or candidate > best:
                second = best
                best = candidate
            elif second is None or candidate > second:
                second = candidate

    if best is None or best[0] < 0.62:
        return None, 0
    if len(reader_ids) == 1:
        return best[2], -best[1]
    if second is not None and best[0] - second[0] < 0.08 and not context["expected_reader_ids"]:
        return None, 0
    return best[2], -best[1]


def resolve_yyyymmdd(candidate: str, context: dict, reader_id: str | None = None) -> str | None:
    token = sanitize_raw_payload(candidate)[:8]
    exact_valid = token if valid_yyyymmdd(token) else None
    known_dates = get_known_dates_for_reader(context, reader_id)
    if exact_valid and exact_valid in known_dates:
        return exact_valid

    def score(date_value: str) -> tuple[float, int, float]:
        digit_matches = sum(1 for raw_ch, date_ch in zip(token, date_value) if raw_ch.isdigit() and raw_ch == date_ch)
        known_digit_count = sum(1 for raw_ch in token if raw_ch.isdigit())
        ratio = digit_matches / max(known_digit_count, 1)
        sequence_ratio = SequenceMatcher(None, token.replace("?", "0"), date_value).ratio()
        return ratio, digit_matches, sequence_ratio

    if known_dates:
        ranked = sorted(((score(date_value), date_value) for date_value in known_dates), reverse=True)
        best_score, best_date = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else None
        if best_score[0] >= 0.75 or best_score[1] >= 6:
            if second_score is None or best_score[0] - second_score[0] >= 0.08 or best_score[1] - second_score[1] >= 1:
                if (
                    exact_valid is None
                    or best_date == exact_valid
                    or best_date in context["expected_dates"]
                    or exact_valid not in known_dates
                    or len(known_dates) == 1
                ):
                    return best_date

    return exact_valid


def normalize_parsed_candidate(parsed: dict, context: dict) -> dict | None:
    resolved_reader_id = resolve_reader_id(parsed["reader_id"], context)
    resolved_yyyymmdd = resolve_yyyymmdd(parsed["yyyymmdd"], context, resolved_reader_id)
    if resolved_yyyymmdd is None:
        return None
    return {
        "reader_id": resolved_reader_id,
        "yyyymmdd": resolved_yyyymmdd,
        "raw": f"{resolved_reader_id}|{resolved_yyyymmdd}",
    }


def recover_candidate_payload(raw: str, context: dict) -> dict | None:
    parsed = parse_watermark_payload(raw)
    if parsed is not None:
        return normalize_parsed_candidate(parsed, context)

    reader_id, offset = resolve_reader_from_raw(raw, context)
    if not reader_id:
        return None

    sanitized = sanitize_raw_payload(raw)
    expected_sep = offset + len(reader_id)
    separator_index = next(
        (
            index
            for index in range(max(expected_sep - 1, 0), min(expected_sep + 2, len(sanitized)))
            if sanitized[index] == "|"
        ),
        expected_sep,
    )
    date_fragment = sanitized[separator_index + 1 : separator_index + 9]
    if len(date_fragment) < 8:
        date_fragment = sanitized[expected_sep + 1 : expected_sep + 9]
    resolved_yyyymmdd = resolve_yyyymmdd(date_fragment, context, reader_id)
    if not resolved_yyyymmdd:
        return None

    return {
        "reader_id": reader_id,
        "yyyymmdd": resolved_yyyymmdd,
        "raw": f"{reader_id}|{resolved_yyyymmdd}",
    }


def choose_best_parsed_result(parsed_candidates: list[dict]) -> dict:
    raw_counts = Counter(item["raw"] for item in parsed_candidates)
    raw, count = raw_counts.most_common(1)[0]
    if count > 1:
        return next(item for item in parsed_candidates if item["raw"] == raw)

    max_length = max(len(item["raw"]) for item in parsed_candidates)
    padded = [item["raw"].ljust(max_length, "~") for item in parsed_candidates]
    consensus_raw = "".join(
        Counter(candidate[index] for candidate in padded).most_common(1)[0][0]
        for index in range(max_length)
    )
    parsed = parse_watermark_payload(consensus_raw)
    if parsed is not None:
        return parsed_candidates[0] if parsed["raw"] == parsed_candidates[0]["raw"] else parsed
    return parsed_candidates[0]


def recover_from_raw_candidates(raw_candidates: list[str], context: dict) -> dict | None:
    sanitized_candidates = [sanitize_raw_payload(raw) for raw in raw_candidates if raw]
    recovered_candidates = [
        candidate
        for candidate in (recover_candidate_payload(raw, context) for raw in sanitized_candidates)
        if candidate is not None
    ]
    if recovered_candidates:
        return choose_best_parsed_result(recovered_candidates)
    if not sanitized_candidates:
        return None

    max_length = max(len(item) for item in sanitized_candidates)
    padded = [item.ljust(max_length, "~") for item in sanitized_candidates]
    consensus_raw = "".join(
        Counter(candidate[index] for candidate in padded).most_common(1)[0][0]
        for index in range(max_length)
    )
    return recover_candidate_payload(consensus_raw, context)


def build_trace_entry(*, stage: str, label: str, raw: str, parsed: dict | None, duration_ms: int) -> dict:
    return {
        "stage": stage,
        "label": label,
        "raw_preview": sanitize_raw_payload(raw)[:32],
        "success": parsed is not None,
        "duration_ms": duration_ms,
        "message": f"{label} {'成功' if parsed is not None else '未找到有效浮水印'}",
    }


def run_candidate_extraction(candidate_image: np.ndarray, *, stage: str, label: str, context: dict) -> tuple[str, dict | None, dict]:
    started = time.perf_counter()
    try:
        raw, parsed = try_extract_payload(candidate_image)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        trace = {
            "stage": stage,
            "label": label,
            "raw_preview": "",
            "success": False,
            "duration_ms": duration_ms,
            "message": f"{label} 提取失敗：{exc}",
        }
        return "", None, trace

    recovered = normalize_parsed_candidate(parsed, context) if parsed is not None else recover_candidate_payload(raw, context)
    duration_ms = int((time.perf_counter() - started) * 1000)
    trace = build_trace_entry(stage=stage, label=label, raw=raw, parsed=recovered, duration_ms=duration_ms)
    return raw, recovered, trace


def iter_full_image_candidates(image: np.ndarray):
    yield "原圖", image

    padded = pad_carrier_image(image)
    if padded.shape != image.shape:
        yield "原圖補高", padded

    for target_width in (600, 420):
        if image.shape[1] == target_width:
            continue
        if image.shape[1] < max(int(target_width * 0.55), 180):
            continue
        yield f"原圖正規化 {target_width}px", resize_candidate(image, target_width)


def estimate_background_color(image: np.ndarray) -> np.ndarray:
    border_width = min(8, max(image.shape[0] // 40, 4), max(image.shape[1] // 40, 4))
    samples = np.concatenate(
        [
            image[:border_width, :, :].reshape(-1, 3),
            image[-border_width:, :, :].reshape(-1, 3),
            image[:, :border_width, :].reshape(-1, 3),
            image[:, -border_width:, :].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(samples, axis=0)


def iter_component_candidates(image: np.ndarray):
    if image.shape[0] < 260:
        return
    background = estimate_background_color(image)
    diff = np.abs(image.astype(np.int16) - background.astype(np.int16)).sum(axis=2)
    mask = (diff > 24).astype(np.uint8) * 255
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = max((image.shape[0] * image.shape[1]) // 15, 50000)
    boxes = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width * height < min_area:
            continue
        if width < min(260, image.shape[1] // 3):
            continue
        boxes.append((x, y, width, height))

    for index, (x, y, width, height) in enumerate(sorted(boxes, key=lambda item: (item[1], item[0])), start=1):
        crop = image[y : y + height, x : x + width]
        yield f"主體裁切 {index}", crop


def build_anchor_positions(length: int, window: int, *, include_quarters: bool) -> list[int]:
    if window >= length:
        return [0]
    max_start = length - window
    anchors = {0, max_start // 2, max_start}
    if include_quarters and max_start > 60:
        anchors.update({max_start // 4, (max_start * 3) // 4})
    return sorted(max(0, min(max_start, value)) for value in anchors)


def build_window_sizes(image: np.ndarray) -> list[tuple[int, int]]:
    width, height = image.shape[1], image.shape[0]
    width_candidates = {
        width,
        int(width * 0.92),
        int(width * 0.78),
        int(width * 0.64),
        int(width * 0.5),
        min(width, 600),
        min(width, 420),
    }
    height_candidates = {
        height,
        min(height, 720),
        min(height, 560),
        min(height, 420),
        min(height, 320),
        min(height, 260),
        min(height, 220),
        min(height, 180),
        int(height * 0.68),
        int(height * 0.5),
        int(height * 0.36),
        int(height * 0.24),
    }

    sizes: list[tuple[int, int]] = []
    for crop_width in sorted({value for value in width_candidates if value >= 220}, reverse=True):
        for crop_height in sorted(
            {value for value in height_candidates if value >= minimum_carrier_height(crop_width)},
            reverse=True,
        ):
            if crop_width > width or crop_height > height:
                continue
            if crop_width * crop_height < 70000:
                continue
            sizes.append((crop_width, crop_height))

    deduped: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for size in sizes:
        if size in seen:
            continue
        seen.add(size)
        deduped.append(size)
    return deduped[:24]


def iter_window_variants(window: np.ndarray):
    yield "裁切原樣", window

    padded = pad_carrier_image(window)
    if padded.shape != window.shape:
        yield "裁切補高", padded

    for target_width in (600, 420):
        if window.shape[1] < max(int(target_width * 0.55), 180):
            continue
        normalized = resize_candidate(window, target_width)
        yield f"裁切正規化 {target_width}px", normalized


def iter_screenshot_window_candidates(image: np.ndarray):
    height, width = image.shape[0], image.shape[1]
    sizes = build_window_sizes(image)
    rng = random.Random(f"{crop_sampler_seed}:{width}x{height}")
    candidates: list[tuple[str, np.ndarray]] = []

    for crop_width, crop_height in sizes:
        xs = build_anchor_positions(width, crop_width, include_quarters=False)
        ys = build_anchor_positions(height, crop_height, include_quarters=True)
        for x in xs:
            for y in ys:
                window = image[y : y + crop_height, x : x + crop_width]
                for variant_label, variant in iter_window_variants(window):
                    candidates.append((f"視窗裁切 {crop_width}x{crop_height} @ ({x},{y}) / {variant_label}", variant))

    rng.shuffle(candidates)
    candidates.sort(key=lambda item: item[1].shape[0] * item[1].shape[1], reverse=True)
    front = candidates[:120]
    tail = candidates[120:]
    rng.shuffle(tail)
    for label, candidate in (front + tail[: max(0, max_crop_attempts - len(front))]):
        yield label, candidate


def compose_vertical_strip(images: list[np.ndarray], *, overlap: int = 1) -> np.ndarray | None:
    if not images:
        return None
    width = images[0].shape[1]
    if any(image.shape[1] != width for image in images):
        return None
    effective_overlap = max(0, overlap)
    total_height = sum(image.shape[0] for image in images) - effective_overlap * max(len(images) - 1, 0)
    if total_height <= 0:
        return None
    canvas = np.zeros((total_height, width), dtype=np.uint8)
    cursor = 0
    for index, image in enumerate(images):
        if index:
            cursor -= effective_overlap
        height = image.shape[0]
        canvas[cursor : cursor + height, :] = image
        cursor += height
    return canvas


def read_gray_image(path: str) -> np.ndarray | None:
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE)


def build_source_match_candidates(context: dict) -> list[SourceMatchCandidate]:
    today = timezone.localdate()
    recent_cutoff = today - timedelta(days=max(source_match_recent_days, settings.DAILY_CACHE_RETENTION_DAYS + 1))
    queryset = (
        DailyPageCache.objects.select_related("reader", "chapter_version__chapter")
        .filter(for_date__lte=today, for_date__gte=recent_cutoff)
        .order_by("-for_date", "-created_at", "-id")
    )
    if context["expected_reader_ids"]:
        queryset = queryset.filter(reader__username__in=context["expected_reader_ids"])
    if context["expected_dates"]:
        date_values = [
            datetime.strptime(value, "%Y%m%d").date()
            for value in context["expected_dates"]
            if valid_yyyymmdd(value)
        ]
        if date_values:
            queryset = queryset.filter(for_date__in=date_values)

    pages = list(queryset[:source_match_max_recent_pages])
    grouped_pages: dict[tuple[int, str, int, str], list[DailyPageCache]] = defaultdict(list)
    ordered_group_keys: list[tuple[int, str, int, str]] = []
    for page in pages:
        if not page.absolute_path.exists():
            continue
        key = (page.reader_id, page.for_date.strftime("%Y%m%d"), page.chapter_version_id, page.device_profile)
        if key not in grouped_pages:
            ordered_group_keys.append(key)
        grouped_pages[key].append(page)

    candidates: list[SourceMatchCandidate] = []
    for key in ordered_group_keys:
        group = grouped_pages[key]
        ordered = sorted(group, key=lambda item: item.page_index)
        for page in ordered:
            gray_image = read_gray_image(str(page.absolute_path))
            if gray_image is None:
                continue
            candidates.append(
                SourceMatchCandidate(
                    label=(
                        f"近期單頁 {page.reader.reader_id} {page.for_date:%Y%m%d} "
                        f"{page.get_device_profile_display()} 第 {page.page_index} 頁"
                    ),
                    reader_id=page.reader.reader_id,
                    yyyymmdd=page.for_date.strftime("%Y%m%d"),
                    gray_image=gray_image,
                    canvas_shape=(gray_image.shape[0], gray_image.shape[1]),
                )
            )
        for page_count in (2, 3):
            if len(ordered) < page_count:
                continue
            for start_index in range(0, len(ordered) - page_count + 1):
                bundle = ordered[start_index : start_index + page_count]
                expected_indexes = list(range(bundle[0].page_index, bundle[0].page_index + page_count))
                if [page.page_index for page in bundle] != expected_indexes:
                    continue
                source_images = []
                for page in bundle:
                    gray_image = read_gray_image(str(page.absolute_path))
                    if gray_image is None:
                        source_images = []
                        break
                    source_images.append(gray_image)
                if not source_images:
                    continue
                composite = compose_vertical_strip(source_images, overlap=1)
                if composite is None:
                    continue
                first_page = bundle[0]
                candidates.append(
                    SourceMatchCandidate(
                        label=(
                            f"近期連續 {page_count} 頁 {first_page.reader.reader_id} {first_page.for_date:%Y%m%d} "
                            f"{first_page.get_device_profile_display()} 第 {bundle[0].page_index}-{bundle[-1].page_index} 頁"
                        ),
                        reader_id=first_page.reader.reader_id,
                        yyyymmdd=first_page.for_date.strftime("%Y%m%d"),
                        gray_image=composite,
                        canvas_shape=(composite.shape[0], composite.shape[1]),
                    )
                )
    return candidates[: source_match_max_recent_pages * 2]


def build_source_probe_boxes(width: int, height: int) -> list[tuple[int, int, int, int]]:
    min_width = min(220, width)
    min_height = min(minimum_carrier_height(width), height)
    boxes: set[tuple[int, int, int, int]] = {(0, 0, width, height)}

    def add_box(crop_width: int, crop_height: int, x: int, y: int) -> None:
        crop_width = max(min_width, min(width, crop_width))
        crop_height = max(min_height, min(height, crop_height))
        x = max(0, min(width - crop_width, x))
        y = max(0, min(height - crop_height, y))
        if crop_width * crop_height >= 70000:
            boxes.add((x, y, crop_width, crop_height))

    add_box(
        int(width * 0.96),
        int(height * 0.96),
        (width - int(width * 0.96)) // 2,
        (height - int(height * 0.96)) // 2,
    )

    for height_ratio in (0.85, 0.68, 0.52):
        crop_height = int(height * height_ratio)
        for y in build_anchor_positions(height, crop_height, include_quarters=True):
            add_box(width, crop_height, 0, y)

    for width_ratio in (0.92, 0.78, 0.64):
        crop_width = int(width * width_ratio)
        crop_height = int(height * 0.72)
        for x in build_anchor_positions(width, crop_width, include_quarters=True):
            add_box(crop_width, crop_height, x, max(0, (height - crop_height) // 2))

    rng = random.Random(f"{crop_sampler_seed}:source:{width}x{height}")
    while len(boxes) < source_match_probe_limit:
        crop_width = rng.randint(max(min_width, int(width * 0.58)), width)
        crop_height = rng.randint(max(min_height, int(height * 0.32)), height)
        if crop_width * crop_height < 70000:
            continue
        x = rng.randint(0, max(0, width - crop_width))
        y = rng.randint(0, max(0, height - crop_height))
        boxes.add((x, y, crop_width, crop_height))

    sorted_boxes = sorted(boxes, key=lambda item: (item[2] * item[3], item[1], item[0]), reverse=True)
    return sorted_boxes[:source_match_probe_limit]


def build_source_match_probes(image: np.ndarray) -> list[SourceProbe]:
    probes: list[SourceProbe] = []
    for index, (x, y, width, height) in enumerate(build_source_probe_boxes(image.shape[1], image.shape[0]), start=1):
        probe = image[y : y + height, x : x + width]
        probes.append(
            SourceProbe(
                label=f"探針 {index} {width}x{height} @ ({x},{y})",
                color_image=probe.copy(),
                gray_image=cv2.cvtColor(probe, cv2.COLOR_BGR2GRAY),
            )
        )
    return probes


def find_template_match_hits(source_gray: np.ndarray, probe_gray: np.ndarray) -> list[TemplateMatchHit]:
    source_h, source_w = source_gray.shape[:2]
    probe_h, probe_w = probe_gray.shape[:2]
    max_scale = min(source_w / probe_w, source_h / probe_h)
    if max_scale < 0.35:
        return []

    base_scales = [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.67, 0.5, 1.05]
    scales = {
        round(scale, 3)
        for scale in base_scales
        if 0.35 <= scale <= max_scale + 0.001
    }
    scales.add(round(min(max_scale, 1.0), 3))
    scales = sorted(scales, reverse=True)

    raw_hits: list[TemplateMatchHit] = []
    for scale in scales:
        scaled_w = max(1, int(probe_w * scale))
        scaled_h = max(1, int(probe_h * scale))
        if scaled_w > source_w or scaled_h > source_h:
            continue
        if scaled_w < 80 or scaled_h < 80:
            continue
        if abs(scale - 1.0) < 1e-6:
            scaled_probe = probe_gray
        else:
            scaled_probe = cv2.resize(probe_gray, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)

        scores = cv2.matchTemplate(source_gray, scaled_probe, cv2.TM_CCOEFF_NORMED)
        if scores.size == 0:
            continue

        flat_scores = scores.reshape(-1)
        top_k = min(source_match_top_hits, flat_scores.size)
        if top_k <= 0:
            continue
        top_indices = np.argpartition(flat_scores, -top_k)[-top_k:]
        for flat_index in top_indices:
            y, x = np.unravel_index(int(flat_index), scores.shape)
            raw_hits.append(
                TemplateMatchHit(
                    x=int(x),
                    y=int(y),
                    score=float(scores[y, x]),
                    scale=float(scale),
                    probe_width=int(scaled_w),
                    probe_height=int(scaled_h),
                )
            )

    hits: list[TemplateMatchHit] = []
    for hit in sorted(raw_hits, key=lambda item: item.score, reverse=True):
        if any(
            abs(hit.x - existing.x) <= 6
            and abs(hit.y - existing.y) <= 6
            and abs(hit.probe_width - existing.probe_width) <= 8
            and abs(hit.probe_height - existing.probe_height) <= 8
            for existing in hits
        ):
            continue
        hits.append(hit)
    return hits[: source_match_top_hits * 3]


def build_local_offsets(radius: int = 1) -> list[tuple[int, int]]:
    offsets = [(0, 0)]
    for current_radius in range(1, radius + 1):
        for dy in range(-current_radius, current_radius + 1):
            for dx in range(-current_radius, current_radius + 1):
                if dx == 0 and dy == 0:
                    continue
                if max(abs(dx), abs(dy)) != current_radius:
                    continue
                offsets.append((dx, dy))
    return offsets


def recover_probe_canvas(
    probe_image: np.ndarray,
    *,
    x: int,
    y: int,
    canvas_shape: tuple[int, int],
) -> np.ndarray | None:
    height, width = probe_image.shape[0], probe_image.shape[1]
    canvas_height, canvas_width = canvas_shape
    if x < 0 or y < 0 or x + width > canvas_width or y + height > canvas_height:
        return None
    canvas = np.zeros((canvas_height, canvas_width, 3), dtype=np.uint8)
    canvas[y : y + height, x : x + width, :] = probe_image
    return canvas


def build_source_match_result(
    *,
    parsed: dict,
    trace: list[dict],
    attempt_count: int,
    duration_ms: int,
    selected_method: str,
    image: np.ndarray,
) -> dict:
    return {
        "raw_payload": parsed["raw"],
        "parsed": parsed,
        "trace": trace,
        "attempt_count": attempt_count,
        "duration_ms": duration_ms,
        "selected_method": selected_method,
        "is_valid": True,
        "image_width": image.shape[1],
        "image_height": image.shape[0],
    }


def choose_metadata_match(metadata_votes: list[dict], context: dict) -> dict | None:
    if not metadata_votes:
        return None

    grouped: dict[str, list[dict]] = defaultdict(list)
    for vote in metadata_votes:
        grouped[f"{vote['reader_id']}|{vote['yyyymmdd']}"].append(vote)

    ranked_groups = sorted(
        grouped.values(),
        key=lambda items: (
            len(items),
            sum(item["score"] for item in items),
            max(item["score"] for item in items),
        ),
        reverse=True,
    )
    best_group = ranked_groups[0]
    best_vote = max(best_group, key=lambda item: item["score"])
    if best_vote["score"] < source_match_metadata_score and len(best_group) < 2:
        return None

    parsed = normalize_parsed_candidate(
        {
            "reader_id": best_vote["reader_id"],
            "yyyymmdd": best_vote["yyyymmdd"],
            "raw": f"{best_vote['reader_id']}|{best_vote['yyyymmdd']}",
        },
        context,
    )
    if parsed is None:
        return None
    return {
        "parsed": parsed,
        "label": best_vote["label"],
        "score": best_vote["score"],
        "votes": len(best_group),
    }


def extract_watermark_from_bytes(
    file_bytes: bytes,
    *,
    allow_crops: bool = True,
    expected_reader_ids: list[str] | None = None,
    expected_dates: list[str] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    np_buffer = np.frombuffer(file_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    if image is None:
        return {
            "raw_payload": "",
            "parsed": None,
            "trace": [
                {
                    "stage": "input",
                    "label": "讀取上傳圖片",
                    "success": False,
                    "duration_ms": 0,
                    "message": "無法讀取圖片內容。",
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
    context = build_recovery_context(expected_reader_ids=expected_reader_ids, expected_dates=expected_dates)
    trace = [
        {
            "stage": "input",
            "label": "讀取上傳圖片",
            "success": True,
            "duration_ms": 0,
            "message": f"圖片尺寸 {image.shape[1]}x{image.shape[0]}",
        }
    ]
    if progress_callback:
        progress_callback(trace[0])

    raw_candidates: list[str] = []
    parsed_candidates: list[dict] = []
    attempt_count = 0

    def assert_not_stopped() -> None:
        if should_stop and should_stop():
            raise ExtractionStopped("Extraction canceled by user.")

    def add_trace(entry: dict) -> None:
        trace.append(entry)
        if progress_callback and (
            entry["success"]
            or entry["stage"] in {"input", "source_match"}
            or attempt_count <= 5
            or attempt_count % 25 == 0
        ):
            progress_callback(entry)

    for label, candidate in iter_full_image_candidates(image):
        assert_not_stopped()
        attempt_count += 1
        raw, parsed, attempt_trace = run_candidate_extraction(candidate, stage="full_image", label=label, context=context)
        raw_candidates.append(raw)
        add_trace(attempt_trace)
        if parsed is not None:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return build_source_match_result(
                parsed=parsed,
                trace=trace,
                attempt_count=attempt_count,
                duration_ms=duration_ms,
                selected_method=label,
                image=image,
            )

    recovered = recover_from_raw_candidates(raw_candidates, context)
    if recovered is not None:
        add_trace(
            {
                "stage": "full_image",
                "label": "原圖結果修復",
                "success": True,
                "duration_ms": 0,
                "message": "原圖提取雖未完全命中，但已從多次結果修復出有效浮水印。",
                "raw_preview": recovered["raw"],
            }
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return build_source_match_result(
            parsed=recovered,
            trace=trace,
            attempt_count=attempt_count,
            duration_ms=duration_ms,
            selected_method="原圖結果修復",
            image=image,
        )

    if allow_crops:
        assert_not_stopped()
        source_candidates = build_source_match_candidates(context)
        probes = build_source_match_probes(image)
        add_trace(
            {
                "stage": "source_match",
                "label": "進入來源對位",
                "success": False,
                "duration_ms": 0,
                "message": (
                    f"改用近期個人化頁圖做來源對位，候選來源 {len(source_candidates)} 組，"
                    f"探針 {len(probes)} 組。"
                ),
                "raw_preview": "",
            }
        )

        source_metadata_votes: list[dict] = []
        local_offsets = build_local_offsets(radius=1)
        for candidate in source_candidates:
            assert_not_stopped()
            for probe in probes:
                assert_not_stopped()
                if probe.gray_image.shape[0] > candidate.gray_image.shape[0] or probe.gray_image.shape[1] > candidate.gray_image.shape[1]:
                    continue
                hits = find_template_match_hits(candidate.gray_image, probe.gray_image)
                if not hits:
                    continue
                best_hit = hits[0]
                if best_hit.score >= source_match_short_circuit_score:
                    parsed = normalize_parsed_candidate(
                        {
                            "reader_id": candidate.reader_id,
                            "yyyymmdd": candidate.yyyymmdd,
                            "raw": f"{candidate.reader_id}|{candidate.yyyymmdd}",
                        },
                        context,
                    )
                    if parsed is not None:
                        add_trace(
                            {
                                "stage": "source_match",
                                "label": "來源精準比對",
                                "success": True,
                                "duration_ms": 0,
                                "message": (
                                    f"與近期個人化頁圖高度一致，直接採用來源比對結果。"
                                    f" 來源：{candidate.label} / {probe.label}"
                                ),
                                "raw_preview": parsed["raw"],
                                "match_score": round(best_hit.score, 6),
                            }
                        )
                        duration_ms = int((time.perf_counter() - started) * 1000)
                        return build_source_match_result(
                            parsed=parsed,
                            trace=trace,
                            attempt_count=attempt_count,
                            duration_ms=duration_ms,
                            selected_method=f"{candidate.label} / {probe.label} / score={best_hit.score:.4f}",
                            image=image,
                        )
                if best_hit.score >= source_match_metadata_score:
                    source_metadata_votes.append(
                        {
                            "reader_id": candidate.reader_id,
                            "yyyymmdd": candidate.yyyymmdd,
                            "score": best_hit.score,
                            "label": f"{candidate.label} / {probe.label}",
                        }
                    )
                for hit in hits:
                    assert_not_stopped()
                    if hit.score < source_match_min_score:
                        continue
                    for dx, dy in local_offsets:
                        assert_not_stopped()
                        probe_color = probe.color_image
                        if (
                            probe_color.shape[1] != hit.probe_width
                            or probe_color.shape[0] != hit.probe_height
                        ):
                            probe_color = cv2.resize(
                                probe_color,
                                (hit.probe_width, hit.probe_height),
                                interpolation=cv2.INTER_LINEAR,
                            )
                        recovered_canvas = recover_probe_canvas(
                            probe_color,
                            x=hit.x + dx,
                            y=hit.y + dy,
                            canvas_shape=candidate.canvas_shape,
                        )
                        if recovered_canvas is None:
                            continue
                        attempt_count += 1
                        label = (
                            f"{candidate.label} / {probe.label} / score={hit.score:.4f} / shift=({dx},{dy})"
                        )
                        raw, parsed, attempt_trace = run_candidate_extraction(
                            recovered_canvas,
                            stage="source_match",
                            label=label,
                            context=context,
                        )
                        raw_candidates.append(raw)
                        attempt_trace["match_score"] = round(hit.score, 6)
                        attempt_trace["reader_hint"] = candidate.reader_id
                        attempt_trace["date_hint"] = candidate.yyyymmdd
                        add_trace(attempt_trace)
                        if parsed is not None:
                            duration_ms = int((time.perf_counter() - started) * 1000)
                            return build_source_match_result(
                                parsed=parsed,
                                trace=trace,
                                attempt_count=attempt_count,
                                duration_ms=duration_ms,
                                selected_method=label,
                                image=image,
                            )

        recovered = recover_from_raw_candidates(raw_candidates, context)
        if recovered is not None:
            add_trace(
                {
                    "stage": "source_match",
                    "label": "來源對位原始資料修復",
                    "success": True,
                    "duration_ms": 0,
                    "message": "來源對位提取雖未直接命中，但已從候選原始資料修復出有效浮水印。",
                    "raw_preview": recovered["raw"],
                }
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            return build_source_match_result(
                parsed=recovered,
                trace=trace,
                attempt_count=attempt_count,
                duration_ms=duration_ms,
                selected_method="來源對位原始資料修復",
                image=image,
            )

        metadata_match = choose_metadata_match(source_metadata_votes, context)
        if metadata_match is not None:
            add_trace(
                {
                    "stage": "source_match",
                    "label": "來源比對回退",
                    "success": True,
                    "duration_ms": 0,
                    "message": (
                        f"直接提取未命中，但來源比對高度一致，採用 {metadata_match['votes']} 次高分比對結果。"
                    ),
                    "raw_preview": metadata_match["parsed"]["raw"],
                    "match_score": round(metadata_match["score"], 6),
                }
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            return build_source_match_result(
                parsed=metadata_match["parsed"],
                trace=trace,
                attempt_count=attempt_count,
                duration_ms=duration_ms,
                selected_method=metadata_match["label"],
                image=image,
            )

        add_trace(
            {
                "stage": "cropped",
                "label": "進入裁切提取",
                "success": False,
                "duration_ms": 0,
                "message": "來源對位未命中，改為嘗試主體裁切與視窗裁切。",
                "raw_preview": "",
            }
        )

        crop_iterators = (
            iter_component_candidates(image),
            iter_screenshot_window_candidates(image),
        )
        for iterator in crop_iterators:
            for label, candidate in iterator:
                assert_not_stopped()
                attempt_count += 1
                raw, parsed, attempt_trace = run_candidate_extraction(candidate, stage="cropped", label=label, context=context)
                raw_candidates.append(raw)
                add_trace(attempt_trace)
                if parsed is not None:
                    parsed_candidates.append(parsed)
                    if len(parsed_candidates) >= 2 and Counter(item["raw"] for item in parsed_candidates).most_common(1)[0][1] >= 2:
                        best = choose_best_parsed_result(parsed_candidates)
                        duration_ms = int((time.perf_counter() - started) * 1000)
                        return build_source_match_result(
                            parsed=best,
                            trace=trace,
                            attempt_count=attempt_count,
                            duration_ms=duration_ms,
                            selected_method=label,
                            image=image,
                        )

        if parsed_candidates:
            best = choose_best_parsed_result(parsed_candidates)
            add_trace(
                {
                    "stage": "cropped",
                    "label": "裁切結果修復",
                    "success": True,
                    "duration_ms": 0,
                    "message": "裁切提取得到多個可疑候選，已合併成最可信結果。",
                    "raw_preview": best["raw"],
                }
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            return build_source_match_result(
                parsed=best,
                trace=trace,
                attempt_count=attempt_count,
                duration_ms=duration_ms,
                selected_method="裁切結果修復",
                image=image,
            )

        recovered = recover_from_raw_candidates(raw_candidates, context)
        if recovered is not None:
            add_trace(
                {
                    "stage": "cropped",
                    "label": "裁切原始資料修復",
                    "success": True,
                    "duration_ms": 0,
                    "message": "直接提取雖失敗，但已從裁切原始結果修復出有效浮水印。",
                    "raw_preview": recovered["raw"],
                }
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            return build_source_match_result(
                parsed=recovered,
                trace=trace,
                attempt_count=attempt_count,
                duration_ms=duration_ms,
                selected_method="裁切原始資料修復",
                image=image,
            )

    duration_ms = int((time.perf_counter() - started) * 1000)
    return {
        "raw_payload": sanitize_raw_payload(raw_candidates[-1]) if raw_candidates else "",
        "parsed": None,
        "trace": trace,
        "attempt_count": attempt_count,
        "duration_ms": duration_ms,
        "selected_method": "",
        "is_valid": False,
        "image_width": image.shape[1],
        "image_height": image.shape[0],
    }


def extract_watermark_from_path(
    image_path: str,
    *,
    allow_crops: bool = True,
    expected_reader_ids: list[str] | None = None,
    expected_dates: list[str] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    with open(image_path, "rb") as image_file:
        return extract_watermark_from_bytes(
            image_file.read(),
            allow_crops=allow_crops,
            expected_reader_ids=expected_reader_ids,
            expected_dates=expected_dates,
            progress_callback=progress_callback,
            should_stop=should_stop,
        )


def extract_watermark_detailed(
    uploaded_file,
    *,
    allow_crops: bool = True,
    expected_reader_ids: list[str] | None = None,
    expected_dates: list[str] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    file_bytes = uploaded_file.read()
    return extract_watermark_from_bytes(
        file_bytes,
        allow_crops=allow_crops,
        expected_reader_ids=expected_reader_ids,
        expected_dates=expected_dates,
        progress_callback=progress_callback,
        should_stop=should_stop,
    )


def extract_watermark(uploaded_file) -> tuple[str, dict | None]:
    result = extract_watermark_detailed(uploaded_file)
    return result["raw_payload"], result["parsed"]


def quick_verify_embedded_watermark(
    image_path: str,
    *,
    expected_reader_id: str | None = None,
    expected_yyyymmdd: str | None = None,
) -> dict:
    image = cv2.imread(image_path, flags=cv2.IMREAD_COLOR)
    if image is None:
        return {"parsed": None, "selected_method": "", "is_valid": False}

    context = build_recovery_context(
        expected_reader_ids=[expected_reader_id] if expected_reader_id else None,
        expected_dates=[expected_yyyymmdd] if expected_yyyymmdd else None,
    )
    for label, candidate in iter_full_image_candidates(image):
        raw, parsed = try_extract_payload(candidate)
        recovered = normalize_parsed_candidate(parsed, context) if parsed is not None else recover_candidate_payload(raw, context)
        if recovered is None:
            continue
        is_valid = bool(
            (expected_reader_id is None or recovered["reader_id"] == expected_reader_id)
            and (expected_yyyymmdd is None or recovered["yyyymmdd"] == expected_yyyymmdd)
        )
        if is_valid:
            return {"parsed": recovered, "selected_method": label, "is_valid": True}
    return {"parsed": None, "selected_method": "", "is_valid": False}


def embed_watermark(
    input_path: str,
    output_path: str,
    payload: str,
    *,
    expected_reader_id: str | None = None,
    expected_yyyymmdd: str | None = None,
) -> dict:
    payload_bits = payload_to_bits(payload)
    verification_trace = []
    last_error = None
    last_meta = None

    for profile in watermark_embed_profiles:
        carrier = build_carrier_image(
            input_path,
            seed=profile["seed"],
            noise_strength=profile["noise_strength"],
            grid_strength=profile["grid_strength"],
        )
        for extra_height in (0, 64, 128):
            watermark = get_watermark_client()
            watermark.read_img(img=pad_carrier_image(carrier, extra_height=extra_height))
            watermark.read_wm(payload_bits, mode="bit")
            try:
                watermark.embed(filename=output_path)
            except AssertionError as exc:
                last_error = exc
                verification_trace.append(
                    {
                        "profile": profile["name"],
                        "extra_height": extra_height,
                        "verified": False,
                        "message": f"嵌入失敗：{exc}",
                    }
                )
                continue

            meta = quick_verify_embedded_watermark(
                output_path,
                expected_reader_id=expected_reader_id,
                expected_yyyymmdd=expected_yyyymmdd,
            )
            verified = bool(
                meta["parsed"] is not None
                and (expected_reader_id is None or meta["parsed"]["reader_id"] == expected_reader_id)
                and (expected_yyyymmdd is None or meta["parsed"]["yyyymmdd"] == expected_yyyymmdd)
            )
            verification_trace.append(
                {
                    "profile": profile["name"],
                    "extra_height": extra_height,
                    "verified": verified,
                    "message": f"{'驗證成功' if verified else '驗證未通過'}，方法：{meta['selected_method'] or 'none'}",
                }
            )
            last_meta = meta
            if verified:
                return {
                    "verified": True,
                    "profile_name": profile["name"],
                    "extra_height": extra_height,
                    "verification_trace": verification_trace,
                    "verification_result": meta,
                }
            break

    if last_error is not None and last_meta is None:
        raise last_error

    return {
        "verified": False,
        "profile_name": watermark_embed_profiles[-1]["name"],
        "extra_height": 128,
        "verification_trace": verification_trace,
        "verification_result": last_meta,
    }


def embed_watermark(
    input_path: str,
    output_path: str,
    payload: str,
    *,
    expected_reader_id: str | None = None,
    expected_yyyymmdd: str | None = None,
) -> dict:
    payload_bits = payload_to_bits(payload)
    verification_trace = []
    last_error = None

    for profile in watermark_embed_profiles:
        carrier = build_carrier_image(
            input_path,
            seed=profile["seed"],
            noise_strength=profile["noise_strength"],
            grid_strength=profile["grid_strength"],
        )
        for extra_height in (0, 64, 128):
            watermark = get_watermark_client()
            watermark.read_img(img=pad_carrier_image(carrier, extra_height=extra_height))
            watermark.read_wm(payload_bits, mode="bit")
            try:
                watermark.embed(filename=output_path)
            except AssertionError as exc:
                last_error = exc
                verification_trace.append(
                    {
                        "profile": profile["name"],
                        "extra_height": extra_height,
                        "verified": False,
                        "message": f"embed failed: {exc}",
                    }
                )
                continue

            verification_trace.append(
                {
                    "profile": profile["name"],
                    "extra_height": extra_height,
                    "verified": True,
                    "message": "embed completed",
                }
            )
            return {
                "verified": True,
                "profile_name": profile["name"],
                "extra_height": extra_height,
                "verification_trace": verification_trace,
                "verification_result": {
                    "parsed": {
                        "reader_id": expected_reader_id or "",
                        "yyyymmdd": expected_yyyymmdd or "",
                    },
                    "selected_method": "embed-only",
                    "is_valid": True,
                },
            }

    if last_error is not None:
        raise last_error

    return {
        "verified": False,
        "profile_name": watermark_embed_profiles[-1]["name"],
        "extra_height": 128,
        "verification_trace": verification_trace,
        "verification_result": {
            "parsed": None,
            "selected_method": "",
            "is_valid": False,
        },
    }
