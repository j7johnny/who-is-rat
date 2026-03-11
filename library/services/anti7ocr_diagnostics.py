from __future__ import annotations

from datetime import datetime
import hashlib
import random
from typing import Any

import numpy as np
from anti7ocr.api import evaluate, generate
from anti7ocr.pipeline.context import PipelineContext
from anti7ocr.pipeline.stages.layout import LayoutStage
from anti7ocr.sensitive import run_sensitive_check
from django.conf import settings

from library.models import AntiOcrPreset

from .anti7ocr_config import build_runtime_config
from .antiocr import normalize_content
from .storage import ensure_parent, media_relative

DEFAULT_PREVIEW_TEXT = (
    "這是一張 anti7ocr 預覽圖，主要用來確認字級、行距、背景干擾與碎裂效果是否仍然方便閱讀。"
    "預設策略以順利閱讀為主，防 OCR 為輔，因此不會啟用中文字倒轉或局部拼音。"
)


def _diagnostic_seed(text: str, device_profile: str) -> int:
    seed_source = f"diagnostic\n{device_profile}\n{text}"
    return int(hashlib.sha256(seed_source.encode("utf-8")).hexdigest()[:8], 16)


def _estimate_height(text: str, config: dict[str, Any], seed: int) -> int:
    ctx = PipelineContext(
        text=text,
        config=config,
        py_rng=random.Random(seed),
        np_rng=np.random.default_rng(seed),
        seed=seed,
        metadata={},
    )
    ctx = LayoutStage()(ctx)
    line_count = max((token.line_index for token in ctx.layout.tokens), default=-1) + 1
    line_count = max(line_count, 1)
    max_size = int(config["font"].get("max_size", 24))
    line_height_multiplier = float(config["layout"].get("line_height_multiplier", 1.4))
    margin = int(config["canvas"].get("margin", 16))
    estimated = int(margin * 2 + line_count * max_size * line_height_multiplier + max_size * 2)
    return max(int(config["canvas"].get("height", estimated)), estimated)


def generate_preview(
    *,
    snapshot: dict[str, Any],
    text: str,
    device_profile: str,
    seed: int | None = None,
    output_prefix: str = "preview",
    font_paths_override: list[str] | None = None,
) -> dict[str, Any]:
    normalized_text = normalize_content(text) or DEFAULT_PREVIEW_TEXT
    runtime_seed = seed if seed is not None else _diagnostic_seed(normalized_text, device_profile)
    runtime_config = build_runtime_config(snapshot, device_profile, enable_sensitive_check=False)
    if font_paths_override:
        runtime_config.setdefault("font", {})
        runtime_config["font"]["paths"] = list(font_paths_override)
        runtime_config["font"]["directories"] = []
        runtime_config["font"]["fallback_to_default"] = True
    runtime_config["canvas"]["height"] = _estimate_height(normalized_text, runtime_config, runtime_seed)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    relative_path = media_relative(
        "anti7ocr_previews",
        timestamp,
        f"{output_prefix}_{device_profile}_{runtime_seed}.png",
    )
    absolute_path = ensure_parent(relative_path)
    result = generate(
        normalized_text,
        config=runtime_config,
        seed=runtime_seed,
        output_options={"path": absolute_path, "format": "PNG"},
    )
    return {
        "seed": runtime_seed,
        "relative_path": relative_path,
        "absolute_path": str(absolute_path),
        "image_url": f"{settings.MEDIA_URL}{relative_path}",
        "metadata": result.metadata,
        "font_paths": list(runtime_config.get("font", {}).get("paths", [])),
    }


def run_diagnostics(
    *,
    text: str,
    preset: AntiOcrPreset,
    device_profile: str,
    seed: int | None = None,
    sensitive_keywords: list[str] | None = None,
) -> dict[str, Any]:
    preview = generate_preview(
        snapshot=preset.as_snapshot(),
        text=text,
        device_profile=device_profile,
        seed=seed,
        output_prefix=f"preset_{preset.id}",
    )
    normalized_text = normalize_content(text) or DEFAULT_PREVIEW_TEXT

    report = evaluate([preview["absolute_path"]], [normalized_text], backends=["tesseract"])
    sample = report.samples[0]
    sensitive_result = {
        "enabled": False,
        "backend": None,
        "recognized_text": "",
        "detected": False,
        "detected_keywords": [],
        "error": None,
    }
    keywords = list(sensitive_keywords or [])
    if keywords:
        runtime_config = build_runtime_config(
            preset.as_snapshot(),
            device_profile,
            enable_sensitive_check=True,
            sensitive_keywords=keywords,
        )
        runtime_config["canvas"]["height"] = _estimate_height(normalized_text, runtime_config, preview["seed"])
        image_result = generate(normalized_text, config=runtime_config, seed=preview["seed"])
        sensitive_result = run_sensitive_check(
            image_result.image,
            {
                "enable": True,
                "backend": "tesseract",
                "keywords": keywords,
                "case_sensitive": True,
            },
        )

    return {
        "seed": preview["seed"],
        "relative_path": preview["relative_path"],
        "absolute_path": preview["absolute_path"],
        "image_url": preview["image_url"],
        "metadata": preview["metadata"],
        "recognized_text": sample.recognized.get("tesseract", ""),
        "cer": sample.cer.get("tesseract", 1.0),
        "errors": sample.errors,
        "avg_cer": report.avg_cer,
        "sensitive_check": sensitive_result,
    }
