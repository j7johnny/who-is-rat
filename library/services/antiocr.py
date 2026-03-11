from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import random
import re
from typing import Any

import numpy as np
from anti7ocr.pipeline import PipelineEngine
from anti7ocr.pipeline.context import PipelineContext
from anti7ocr.pipeline.stages.layout import LayoutStage
from django.conf import settings
from PIL import Image

from library.models import AntiOcrPreset, BasePage, ChapterVersion, DeviceProfile

from .anti7ocr_config import (
    DEFAULT_BASE_PRESET_NAME,
    build_default_desktop_config,
    build_default_mobile_config,
    build_default_shared_config,
    build_runtime_config,
    normalize_preset_snapshot,
)
from .font_library import list_runtime_font_paths
from .storage import delete_relative_path, ensure_parent, media_relative

cjk_char_pattern = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
horizontal_space_pattern = re.compile(r"[ \t]+")
base_page_layout_version = "v5"


@dataclass(frozen=True)
class RenderProfile:
    code: str
    width: int
    initial_height: int
    slice_target_height: int
    min_slice_height: int
    min_watermark_height: int
    first_page_min_cn: int = 200


@dataclass(frozen=True)
class RenderedLine:
    index: int
    top: int
    bottom: int
    text: str
    char_count: int


@dataclass(frozen=True)
class SlicePlan:
    start: int
    end: int
    char_count: int


profile_targets = {
    DeviceProfile.DESKTOP: {
        "slice_target_height": 290,
        "min_slice_height": 96,
        "min_watermark_height": 180,
    },
    DeviceProfile.MOBILE: {
        "slice_target_height": 250,
        "min_slice_height": 110,
        "min_watermark_height": 220,
    },
}


def get_default_preset() -> AntiOcrPreset:
    preset, _ = AntiOcrPreset.objects.get_or_create(
        is_default=True,
        defaults={
            "name": "網站預設（anti7ocr 可讀性優先）",
            "base_preset_name": DEFAULT_BASE_PRESET_NAME,
            "shared_config": build_default_shared_config(),
            "desktop_config": build_default_desktop_config(),
            "mobile_config": build_default_mobile_config(),
        },
    )
    return preset


def build_source_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def resolve_font_paths() -> list[str]:
    usable = list_runtime_font_paths()
    if not usable:
        raise FileNotFoundError("No usable anti7ocr font file was found.")
    return usable


def count_cn_chars(text: str) -> int:
    return len(cjk_char_pattern.findall(text))


def normalize_content(content: str) -> str:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized_lines: list[str] = []
    blank_run = 0
    for raw_line in lines:
        line = horizontal_space_pattern.sub(" ", raw_line).strip()
        if line:
            blank_run = 0
            normalized_lines.append(line)
            continue
        if blank_run == 0:
            normalized_lines.append("")
        blank_run += 1

    while normalized_lines and not normalized_lines[0]:
        normalized_lines.pop(0)
    while normalized_lines and not normalized_lines[-1]:
        normalized_lines.pop()
    return "\n".join(normalized_lines).strip()


def build_render_profile(snapshot: dict[str, Any], device_profile: str) -> RenderProfile:
    normalized = normalize_preset_snapshot(snapshot)
    profile_snapshot = normalized["desktop_config"] if device_profile == DeviceProfile.DESKTOP else normalized["mobile_config"]
    targets = profile_targets[device_profile]
    return RenderProfile(
        code=device_profile,
        width=int(profile_snapshot["canvas"]["width"]),
        initial_height=int(profile_snapshot["canvas"]["height"]),
        slice_target_height=targets["slice_target_height"],
        min_slice_height=targets["min_slice_height"],
        min_watermark_height=targets["min_watermark_height"],
    )


def build_render_seed(text: str, device_profile: str) -> int:
    seed_source = f"{device_profile}\n{text}"
    return int(hashlib.sha256(seed_source.encode("utf-8")).hexdigest()[:8], 16)


def _make_context(text: str, config: dict[str, Any], seed: int) -> PipelineContext:
    return PipelineContext(
        text=text,
        config=config,
        py_rng=random.Random(seed),
        np_rng=np.random.default_rng(seed),
        seed=seed,
        metadata={},
    )


def _estimate_canvas_height(text: str, runtime_config: dict[str, Any], seed: int) -> int:
    preview_ctx = _make_context(text, runtime_config, seed)
    preview_ctx = LayoutStage()(preview_ctx)
    line_count = max((token.line_index for token in preview_ctx.layout.tokens), default=-1) + 1
    line_count = max(line_count, 1)
    max_size = int(runtime_config["font"].get("max_size", 24))
    line_height_multiplier = float(runtime_config["layout"].get("line_height_multiplier", 1.4))
    margin = int(runtime_config["canvas"].get("margin", 16))
    estimated = int(margin * 2 + line_count * max_size * line_height_multiplier + max_size * 2)
    return max(int(runtime_config["canvas"].get("height", estimated)), estimated)


def render_text_image(content: str, snapshot: dict[str, Any], device_profile: str) -> tuple[Image.Image, dict[str, Any]]:
    normalized_text = normalize_content(content) or " "
    resolve_font_paths()
    runtime_config = build_runtime_config(snapshot, device_profile)
    runtime_config["canvas"]["height"] = _estimate_canvas_height(normalized_text, runtime_config, build_render_seed(normalized_text, device_profile))
    seed = build_render_seed(normalized_text, device_profile)
    ctx = _make_context(normalized_text, runtime_config, seed)
    ctx = PipelineEngine().run(ctx)
    if ctx.image is None or ctx.render is None or ctx.layout is None:
        raise RuntimeError("anti7ocr pipeline did not return an image.")
    return ctx.image, {
        "config": runtime_config,
        "glyphs": list(ctx.render.glyphs),
        "tokens": list(ctx.layout.tokens),
        "metadata": dict(ctx.metadata),
    }


def build_line_infos(render_data: dict[str, Any]) -> list[RenderedLine]:
    tokens_by_line: dict[int, list[str]] = {}
    for token in render_data["tokens"]:
        tokens_by_line.setdefault(token.line_index, []).append(token.char)

    glyphs_by_line: dict[int, list[Any]] = {}
    for glyph in render_data["glyphs"]:
        glyphs_by_line.setdefault(glyph.line_index, []).append(glyph)

    lines: list[RenderedLine] = []
    for line_index in sorted(glyphs_by_line):
        glyphs = glyphs_by_line[line_index]
        if not glyphs:
            continue
        top = min(glyph.bbox[1] for glyph in glyphs)
        bottom = max(glyph.bbox[3] for glyph in glyphs)
        text = "".join(tokens_by_line.get(line_index, []))
        lines.append(
            RenderedLine(
                index=line_index,
                top=top,
                bottom=bottom,
                text=text,
                char_count=count_cn_chars(text),
            )
        )
    return lines


def _cut_position(current_line: RenderedLine, next_line: RenderedLine | None, image_height: int) -> int:
    if next_line is None:
        return image_height
    return min(image_height, max(current_line.bottom, (current_line.bottom + next_line.top) // 2))


def build_slice_plans(lines: list[RenderedLine], image_height: int, profile: RenderProfile) -> list[SlicePlan]:
    if not lines:
        return [SlicePlan(start=0, end=image_height, char_count=0)]

    total_cn_chars = sum(line.char_count for line in lines)
    first_page_target = profile.first_page_min_cn if total_cn_chars >= profile.first_page_min_cn else 0
    plans: list[SlicePlan] = []
    start = 0
    page_char_count = 0
    start_line_index = 0

    for index, line in enumerate(lines):
        page_char_count += line.char_count
        cut = _cut_position(line, lines[index + 1] if index + 1 < len(lines) else None, image_height)
        current_height = cut - start
        remaining_height = image_height - cut
        first_page_ready = bool(plans) or first_page_target == 0 or page_char_count >= first_page_target
        should_cut = (
            current_height >= profile.slice_target_height
            and first_page_ready
            and remaining_height >= profile.min_slice_height
        )
        if should_cut:
            plans.append(SlicePlan(start=start, end=cut, char_count=page_char_count))
            start = cut
            page_char_count = 0
            start_line_index = index + 1

    if start_line_index < len(lines):
        plans.append(SlicePlan(start=start, end=image_height, char_count=page_char_count))

    if len(plans) > 1 and plans[-1].end - plans[-1].start < profile.min_slice_height:
        last = plans.pop()
        previous = plans.pop()
        plans.append(SlicePlan(start=previous.start, end=last.end, char_count=previous.char_count + last.char_count))

    return plans


def pad_page_image(image: Image.Image, min_height: int) -> Image.Image:
    if image.height >= min_height:
        return image

    fill_height = min_height - image.height
    tail_height = min(8, image.height) or 1
    tail_strip = image.crop((0, image.height - tail_height, image.width, image.height))
    filler = tail_strip.resize((image.width, fill_height))
    padded = Image.new(image.mode, (image.width, min_height))
    padded.paste(image, (0, 0))
    padded.paste(filler, (0, image.height))
    return padded


def render_chapter_page_images(content: str, snapshot: dict[str, Any], device_profile: str) -> list[tuple[Image.Image, int]]:
    profile = build_render_profile(snapshot, device_profile)
    chapter_image, render_data = render_text_image(content, snapshot, device_profile)
    try:
        line_infos = build_line_infos(render_data)
        slice_plans = build_slice_plans(line_infos, chapter_image.height, profile)
        pages: list[tuple[Image.Image, int]] = []
        for plan in slice_plans:
            page_image = chapter_image.crop((0, plan.start, chapter_image.width, plan.end)).copy()
            page_image = pad_page_image(page_image, profile.min_watermark_height)
            pages.append((page_image, plan.char_count))
        return pages
    finally:
        chapter_image.close()


def base_page_relative_path(chapter_version_id: int, device_profile: str, page_index: int) -> str:
    return media_relative(
        "base_pages",
        base_page_layout_version,
        f"version_{chapter_version_id}",
        device_profile,
        f"page_{page_index:04d}.png",
    )


def base_pages_need_regeneration(pages: list[BasePage], device_profile: str, snapshot: dict[str, Any]) -> bool:
    if not pages:
        return True

    profile = build_render_profile(snapshot, device_profile)
    expected_prefix = f"base_pages/{base_page_layout_version}/"
    for page in pages:
        if not page.relative_path.startswith(expected_prefix):
            return True
        if not page.absolute_path.exists():
            return True
        if page.image_height < profile.min_watermark_height:
            return True
        if page.image_width > profile.width:
            return True
    return False


def save_base_page_image(
    chapter_version: ChapterVersion,
    device_profile: str,
    page_index: int,
    image: Image.Image,
    char_count: int,
) -> BasePage:
    relative_path = base_page_relative_path(chapter_version.id, device_profile, page_index)
    absolute_path = ensure_parent(relative_path)
    image.save(absolute_path, format="PNG")

    existing = BasePage.objects.filter(
        chapter_version=chapter_version,
        device_profile=device_profile,
        page_index=page_index,
    ).first()
    if existing and existing.relative_path != relative_path:
        delete_relative_path(existing.relative_path)

    page, _ = BasePage.objects.update_or_create(
        chapter_version=chapter_version,
        device_profile=device_profile,
        page_index=page_index,
        defaults={
            "relative_path": relative_path,
            "char_count": char_count,
            "image_width": image.width,
            "image_height": image.height,
        },
    )
    return page
