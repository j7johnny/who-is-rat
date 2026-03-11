"""Backend registry."""

from __future__ import annotations

from .base import OCRBackend
from .cnocr_backend import CnOCRBackend
from .static_backend import StaticBackend
from .tesseract_backend import TesseractBackend


def build_backend(name: str) -> OCRBackend:
    normalized = name.lower().strip()
    if normalized == "noop":
        return StaticBackend("")
    if normalized.startswith("static:"):
        return StaticBackend(name.split(":", 1)[1])
    if normalized == "tesseract":
        return TesseractBackend()
    if normalized == "cnocr":
        return CnOCRBackend()
    raise ValueError(f"Unknown OCR backend: {name}")


__all__ = ["OCRBackend", "build_backend", "TesseractBackend", "CnOCRBackend", "StaticBackend"]
