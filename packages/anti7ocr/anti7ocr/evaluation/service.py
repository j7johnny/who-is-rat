"""OCR evaluation service."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image

from ..models import EvalReport, EvalSampleResult
from .backends import OCRBackend, build_backend
from .metrics import cer


def evaluate_images(
    *,
    images: Iterable[Image.Image | str | Path],
    gt_texts: Iterable[str],
    backends: Iterable[str | OCRBackend],
) -> EvalReport:
    backend_instances: list[OCRBackend] = []
    for backend in backends:
        if isinstance(backend, OCRBackend):
            backend_instances.append(backend)
        else:
            backend_instances.append(build_backend(str(backend)))

    sample_results: list[EvalSampleResult] = []
    aggregate: dict[str, list[float]] = {backend.name: [] for backend in backend_instances}

    for idx, (image_obj, gt) in enumerate(zip(images, gt_texts)):
        image = _to_image(image_obj)
        recognized: dict[str, str] = {}
        cer_scores: dict[str, float] = {}
        errors: dict[str, str] = {}
        for backend in backend_instances:
            try:
                predicted = backend.recognize(image)
                score = cer(gt, predicted)
            except Exception as exc:
                predicted = ""
                score = 1.0
                errors[backend.name] = str(exc)
            recognized[backend.name] = predicted
            cer_scores[backend.name] = score
            aggregate[backend.name].append(score)
        sample_results.append(
            EvalSampleResult(
                sample_id=f"sample_{idx:04d}",
                ground_truth=gt,
                recognized=recognized,
                cer=cer_scores,
                errors=errors,
            )
        )

    avg = {
        backend_name: (sum(values) / len(values) if values else 0.0)
        for backend_name, values in aggregate.items()
    }
    return EvalReport(samples=sample_results, avg_cer=avg)


def _to_image(value: Image.Image | str | Path) -> Image.Image:
    if isinstance(value, Image.Image):
        return value.convert("RGB")
    return Image.open(Path(value)).convert("RGB")
