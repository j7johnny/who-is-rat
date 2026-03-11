from __future__ import annotations

from pathlib import Path

from django.conf import settings


def _dedupe_paths(paths: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = str(Path(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def list_active_custom_font_paths() -> list[str]:
    from library.models import CustomFontUpload

    paths: list[str] = []
    for font in CustomFontUpload.objects.filter(is_active=True).order_by("name"):
        try:
            path = font.absolute_path
        except Exception:
            continue
        if path.is_file():
            paths.append(str(path))
    return paths


def list_runtime_font_paths() -> list[str]:
    configured = [path for path in settings.ANTI_OCR_FONT_PATHS if path and Path(path).is_file()]
    uploaded = list_active_custom_font_paths()
    return _dedupe_paths(uploaded + configured)
