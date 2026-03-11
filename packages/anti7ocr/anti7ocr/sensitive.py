"""Sensitive keyword detection helpers."""

from __future__ import annotations

from PIL import Image

from .evaluation.backends import build_backend


def run_sensitive_check(image: Image.Image, config: dict) -> dict:
    """Run OCR-based sensitive keyword detection on an image."""

    enabled = bool(config.get("enable", False))
    if not enabled:
        return {
            "enabled": False,
            "backend": None,
            "recognized_text": "",
            "detected": False,
            "detected_keywords": [],
            "error": None,
        }

    keywords = [str(item) for item in config.get("keywords", []) if str(item).strip()]
    backend_name = str(config.get("backend", "tesseract"))
    case_sensitive = bool(config.get("case_sensitive", True))
    if not keywords:
        return {
            "enabled": True,
            "backend": backend_name,
            "recognized_text": "",
            "detected": False,
            "detected_keywords": [],
            "error": "No keywords configured",
        }

    try:
        backend = build_backend(backend_name)
        recognized_text = backend.recognize(image)
    except Exception as exc:
        return {
            "enabled": True,
            "backend": backend_name,
            "recognized_text": "",
            "detected": False,
            "detected_keywords": [],
            "error": str(exc),
        }

    text_for_match = recognized_text if case_sensitive else recognized_text.lower()
    detected: list[str] = []
    for keyword in keywords:
        needle = keyword if case_sensitive else keyword.lower()
        if needle in text_for_match:
            detected.append(keyword)

    return {
        "enabled": True,
        "backend": backend_name,
        "recognized_text": recognized_text,
        "detected": bool(detected),
        "detected_keywords": detected,
        "error": None,
    }

