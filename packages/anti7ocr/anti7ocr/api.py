"""Public library API."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Iterable

import numpy as np

from .config import resolve_config
from .evaluation import evaluate_images
from .models import BatchItemResult, BatchResult, EvalReport, GenerationResult
from .pipeline import PipelineEngine
from .pipeline.context import PipelineContext
from .sensitive import run_sensitive_check


def generate(
    text: str,
    *,
    config: dict | None = None,
    preset: str | None = None,
    config_path: str | Path | None = None,
    seed: int | None = None,
    output_options: dict | None = None,
) -> GenerationResult:
    """Generate one anti-OCR image."""

    runtime_seed = seed if seed is not None else random.SystemRandom().randint(1, 2**31 - 1)
    override_cfg = dict(config or {})
    if output_options:
        export_cfg = override_cfg.setdefault("export", {})
        if "format" in output_options:
            export_cfg["format"] = output_options["format"]
    resolved = resolve_config(preset=preset, yaml_path=config_path, overrides=override_cfg)
    sensitive_cfg = resolved.get("sensitive_check", {})
    mode = str(sensitive_cfg.get("mode", "warn")).lower()
    max_attempts = max(1, int(sensitive_cfg.get("max_attempts", 1)))
    if mode not in {"warn", "retry"}:
        raise ValueError("sensitive_check.mode must be one of: warn, retry")

    final_ctx = None
    last_sensitive_result = None
    for attempt in range(max_attempts):
        attempt_seed = runtime_seed + attempt
        py_rng = random.Random(attempt_seed)
        np_rng = np.random.default_rng(attempt_seed)
        ctx = PipelineContext(
            text=text,
            config=resolved,
            py_rng=py_rng,
            np_rng=np_rng,
            seed=attempt_seed,
            metadata={"attempt": attempt + 1},
        )
        if output_options and "path" in output_options:
            ctx.metadata["output_path"] = str(output_options["path"])
        if output_options and "background_image" in output_options:
            ctx.metadata["background_image"] = output_options["background_image"]
        if output_options and "evaluate_callback" in output_options:
            ctx.metadata["evaluate_callback"] = output_options["evaluate_callback"]

        final_ctx = PipelineEngine().run(ctx)
        if final_ctx.image is None:
            raise RuntimeError("Pipeline did not produce an image")

        last_sensitive_result = run_sensitive_check(final_ctx.image, sensitive_cfg)
        final_ctx.metadata["sensitive_check"] = last_sensitive_result
        if not last_sensitive_result.get("enabled", False):
            break
        if not last_sensitive_result.get("detected", False):
            break
        if mode == "warn":
            break

    if final_ctx is None or final_ctx.image is None:
        raise RuntimeError("Pipeline did not produce an image")
    final_ctx.metadata["attempt_count"] = int(final_ctx.metadata.get("attempt", 1))
    if last_sensitive_result is not None:
        final_ctx.metadata["sensitive_check"] = last_sensitive_result

    output_path = Path(final_ctx.metadata["saved_path"]) if "saved_path" in final_ctx.metadata else None
    return GenerationResult(
        image=final_ctx.image,
        seed=runtime_seed,
        output_path=output_path,
        metadata=dict(final_ctx.metadata),
    )


def generate_batch(
    input_source: list[str] | str | Path,
    *,
    config: dict | None = None,
    preset: str | None = None,
    config_path: str | Path | None = None,
    base_seed: int | None = None,
    seed_strategy: str = "incremental",
    output_dir: str | Path = "outputs",
    output_format: str = "PNG",
) -> BatchResult:
    """Generate images in batch."""

    texts = _read_texts(input_source)
    base = base_seed if base_seed is not None else random.SystemRandom().randint(1, 2**31 - 1)
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    items: list[BatchItemResult] = []

    for idx, text in enumerate(texts):
        if seed_strategy == "incremental":
            item_seed = base + idx
        elif seed_strategy == "random":
            item_seed = random.SystemRandom().randint(1, 2**31 - 1)
        else:
            raise ValueError(f"Unknown seed_strategy: {seed_strategy}")
        output_path = out_dir / f"sample_{idx:04d}.{output_format.lower()}"
        result = generate(
            text,
            config=config,
            preset=preset,
            config_path=config_path,
            seed=item_seed,
            output_options={"path": output_path, "format": output_format},
        )
        items.append(
            BatchItemResult(
                item_id=f"sample_{idx:04d}",
                text=text,
                seed=item_seed,
                output_path=result.output_path,
                metadata=result.metadata,
            )
        )

    manifest_path = out_dir / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as file:
        for item in items:
            file.write(
                json.dumps(
                    {
                        "id": item.item_id,
                        "text": item.text,
                        "seed": item.seed,
                        "output_path": str(item.output_path) if item.output_path else None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return BatchResult(items=items, manifest_path=manifest_path)


def evaluate(
    images: Iterable[str | Path],
    gt_texts: Iterable[str],
    *,
    backends: Iterable[str] | None = None,
    metrics: list[str] | None = None,
) -> EvalReport:
    """Evaluate generated images against OCR backends."""

    if metrics and metrics != ["cer"]:
        raise ValueError("Only CER metric is currently supported")
    backend_list = list(backends) if backends is not None else ["tesseract"]
    return evaluate_images(images=images, gt_texts=gt_texts, backends=backend_list)


def _read_texts(source: list[str] | str | Path) -> list[str]:
    if isinstance(source, list):
        return [item for item in source if item is not None]
    path = Path(source).expanduser().resolve()
    texts: list[str] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.rstrip("\n").lstrip("\ufeff")
            if line.strip():
                texts.append(line)
    return texts
