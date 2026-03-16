from __future__ import annotations

from copy import deepcopy
from typing import Any

from anti7ocr.presets import build_preset
from django.conf import settings
from django.core.exceptions import ValidationError

ANTI7OCR_ENGINE_NAME = "anti7ocr"
ANTI7OCR_ENGINE_COMMIT = "451d8ff53ac0801a42236e7d3b27c79710b948d5"
ANTI7OCR_CONFIG_VERSION = 1
DEFAULT_BASE_PRESET_NAME = "tw_readable"
DEFAULT_CANVAS_BACKGROUND_COLOR = [254, 249, 241]
PRESET_NAME_CHOICES = (
    ("tw_readable", "tw_readable"),
    ("tw_balanced", "tw_balanced"),
    ("tw_aggressive", "tw_aggressive"),
    ("tw_hardened", "tw_hardened"),
    ("friendly_read", "friendly_read"),
)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _clone(value: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(value)


def build_default_shared_config() -> dict[str, Any]:
    return {
        "text": {
            "unicode_normalization": "NFC",
            "enable_char_to_pinyin": False,
            "char_to_pinyin_ratio": 0.0,
            "enable_char_reverse": False,
            "char_reverse_ratio": 0.0,
            "reverse_rotation_range": [170, 190],
        },
        "canvas": {
            "background_color": list(DEFAULT_CANVAS_BACKGROUND_COLOR),
            "text_color": [20, 20, 20],
            "dpi": 96,
        },
        "font": {
            "paths": [],
            "directories": [],
            "fallback_to_default": True,
        },
        "background": {
            "enable": True,
            "min_font_size": 10,
            "max_font_size": 24,
            "foreground": [130, 130, 130],
        },
        "fragment": {
            "enable": True,
            "stroke_fragmentation_prob": 0.12,
            "closed_structure_break_prob": 0.14,
            "closed_structure_chars": "日目田由甲申甴電圓回國區圈團圖園門問間關閉器聽讀寫體囗口",
            "erase_width": 1,
            "erase_ratio": 0.04,
            "max_stroke_fragments": 1,
            "max_closed_breaks": 1,
        },
        "perturb": {
            "enable": True,
            "edge_jitter_strength": 0.03,
            "edge_brightness_noise": 8,
            "local_contrast_noise": 0.08,
            "local_contrast_patches": 10,
            "adversarial_watermark_enable": True,
            "watermark_text": "anti7ocr",
            "watermark_opacity": 12,
            "watermark_density": 0.10,
            "watermark_scale": 0.45,
        },
        "export": {
            "format": "PNG",
            "quality": 95,
        },
        "sensitive_check": {
            "enable": False,
            "backend": "tesseract",
            "keywords": [],
            "case_sensitive": True,
            "mode": "warn",
            "max_attempts": 1,
        },
    }


def build_default_desktop_config() -> dict[str, Any]:
    return {
        "canvas": {
            "width": 600,
            "height": 860,
            "margin": 16,
            "supersample": 2,
        },
        "layout": {
            "max_chars_per_line": 26,
            "line_height_multiplier": 1.45,
            "micro_kerning_jitter": 0.8,
            "baseline_jitter": 0.8,
            "character_scale_jitter": 0.04,
        },
        "font": {
            "min_size": 22,
            "max_size": 28,
        },
        "background": {
            "density": 0.08,
        },
    }


def build_default_mobile_config() -> dict[str, Any]:
    return {
        "canvas": {
            "width": 420,
            "height": 760,
            "margin": 12,
            "supersample": 2,
        },
        "layout": {
            "max_chars_per_line": 22,
            "line_height_multiplier": 1.50,
            "micro_kerning_jitter": 0.6,
            "baseline_jitter": 0.6,
            "character_scale_jitter": 0.03,
        },
        "font": {
            "min_size": 20,
            "max_size": 24,
        },
        "background": {
            "density": 0.06,
        },
    }


def default_preset_snapshot() -> dict[str, Any]:
    return {
        "engine": ANTI7OCR_ENGINE_NAME,
        "engine_commit": ANTI7OCR_ENGINE_COMMIT,
        "config_version": ANTI7OCR_CONFIG_VERSION,
        "base_preset_name": DEFAULT_BASE_PRESET_NAME,
        "shared_config": build_default_shared_config(),
        "desktop_config": build_default_desktop_config(),
        "mobile_config": build_default_mobile_config(),
    }


def ensure_color_triplet(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValidationError(f"{field_name} 必須是 3 個整數的陣列。")
    cleaned: list[int] = []
    for item in value:
        cleaned.append(_validate_int(item, field_name, minimum=0, maximum=255))
    return cleaned


def _validate_float(value: Any, field_name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} 必須是數字。") from exc
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field_name} 不可小於 {minimum}。")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field_name} 不可大於 {maximum}。")
    return number


def _validate_int(value: Any, field_name: str, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} 必須是整數。") from exc
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field_name} 不可小於 {minimum}。")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field_name} 不可大於 {maximum}。")
    return number


def _validate_bool(value: Any) -> bool:
    return bool(value)


def sanitize_shared_config(shared_config: dict[str, Any] | None) -> dict[str, Any]:
    config = _clone(build_default_shared_config())
    deep_merge(config, _clone(shared_config or {}))

    text_cfg = config["text"]
    text_cfg["unicode_normalization"] = str(text_cfg.get("unicode_normalization", "NFC"))
    text_cfg["enable_char_to_pinyin"] = _validate_bool(text_cfg.get("enable_char_to_pinyin", False))
    text_cfg["char_to_pinyin_ratio"] = _validate_float(
        text_cfg.get("char_to_pinyin_ratio", 0.0),
        "text.char_to_pinyin_ratio",
        0.0,
        1.0,
    )
    text_cfg["enable_char_reverse"] = _validate_bool(text_cfg.get("enable_char_reverse", False))
    text_cfg["char_reverse_ratio"] = _validate_float(
        text_cfg.get("char_reverse_ratio", 0.0),
        "text.char_reverse_ratio",
        0.0,
        1.0,
    )
    reverse_range = text_cfg.get("reverse_rotation_range", [170, 190])
    if not isinstance(reverse_range, list) or len(reverse_range) != 2:
        raise ValidationError("text.reverse_rotation_range 必須是 2 個整數的陣列。")
    text_cfg["reverse_rotation_range"] = [
        _validate_int(reverse_range[0], "text.reverse_rotation_range[0]", 0, 360),
        _validate_int(reverse_range[1], "text.reverse_rotation_range[1]", 0, 360),
    ]
    if text_cfg["reverse_rotation_range"][0] > text_cfg["reverse_rotation_range"][1]:
        raise ValidationError("text.reverse_rotation_range 起始值不可大於結束值。")

    canvas_cfg = config["canvas"]
    canvas_cfg["background_color"] = ensure_color_triplet(
        canvas_cfg.get("background_color", list(DEFAULT_CANVAS_BACKGROUND_COLOR)),
        "canvas.background_color",
    )
    canvas_cfg["text_color"] = ensure_color_triplet(canvas_cfg.get("text_color", [20, 20, 20]), "canvas.text_color")
    canvas_cfg["dpi"] = _validate_int(canvas_cfg.get("dpi", 96), "canvas.dpi", 72, 600)

    font_cfg = config["font"]
    font_cfg["paths"] = []
    font_cfg["directories"] = []
    font_cfg["fallback_to_default"] = _validate_bool(font_cfg.get("fallback_to_default", True))

    background_cfg = config["background"]
    background_cfg["enable"] = _validate_bool(background_cfg.get("enable", True))
    background_cfg["min_font_size"] = _validate_int(background_cfg.get("min_font_size", 10), "background.min_font_size", 6, 128)
    background_cfg["max_font_size"] = _validate_int(background_cfg.get("max_font_size", 24), "background.max_font_size", 6, 256)
    if background_cfg["min_font_size"] > background_cfg["max_font_size"]:
        raise ValidationError("background.min_font_size 不可大於 background.max_font_size。")
    background_cfg["foreground"] = ensure_color_triplet(background_cfg.get("foreground", [130, 130, 130]), "background.foreground")

    fragment_cfg = config["fragment"]
    fragment_cfg["enable"] = _validate_bool(fragment_cfg.get("enable", True))
    fragment_cfg["stroke_fragmentation_prob"] = _validate_float(fragment_cfg.get("stroke_fragmentation_prob", 0.12), "fragment.stroke_fragmentation_prob", 0.0, 1.0)
    fragment_cfg["closed_structure_break_prob"] = _validate_float(fragment_cfg.get("closed_structure_break_prob", 0.14), "fragment.closed_structure_break_prob", 0.0, 1.0)
    fragment_cfg["closed_structure_chars"] = str(fragment_cfg.get("closed_structure_chars", ""))
    fragment_cfg["erase_width"] = _validate_int(fragment_cfg.get("erase_width", 1), "fragment.erase_width", 0, 16)
    fragment_cfg["erase_ratio"] = _validate_float(fragment_cfg.get("erase_ratio", 0.04), "fragment.erase_ratio", 0.0, 1.0)
    fragment_cfg["max_stroke_fragments"] = _validate_int(fragment_cfg.get("max_stroke_fragments", 1), "fragment.max_stroke_fragments", 0, 8)
    fragment_cfg["max_closed_breaks"] = _validate_int(fragment_cfg.get("max_closed_breaks", 1), "fragment.max_closed_breaks", 0, 8)

    perturb_cfg = config["perturb"]
    perturb_cfg["enable"] = _validate_bool(perturb_cfg.get("enable", True))
    perturb_cfg["edge_jitter_strength"] = _validate_float(perturb_cfg.get("edge_jitter_strength", 0.03), "perturb.edge_jitter_strength", 0.0, 1.0)
    perturb_cfg["edge_brightness_noise"] = _validate_int(perturb_cfg.get("edge_brightness_noise", 8), "perturb.edge_brightness_noise", 0, 255)
    perturb_cfg["local_contrast_noise"] = _validate_float(perturb_cfg.get("local_contrast_noise", 0.08), "perturb.local_contrast_noise", 0.0, 1.0)
    perturb_cfg["local_contrast_patches"] = _validate_int(perturb_cfg.get("local_contrast_patches", 10), "perturb.local_contrast_patches", 0, 1000)
    perturb_cfg["adversarial_watermark_enable"] = _validate_bool(perturb_cfg.get("adversarial_watermark_enable", True))
    perturb_cfg["watermark_text"] = str(perturb_cfg.get("watermark_text", "anti7ocr"))
    perturb_cfg["watermark_opacity"] = _validate_int(perturb_cfg.get("watermark_opacity", 12), "perturb.watermark_opacity", 0, 255)
    perturb_cfg["watermark_density"] = _validate_float(perturb_cfg.get("watermark_density", 0.10), "perturb.watermark_density", 0.0, 1.0)
    perturb_cfg["watermark_scale"] = _validate_float(perturb_cfg.get("watermark_scale", 0.45), "perturb.watermark_scale", 0.0, 5.0)

    export_cfg = config["export"]
    export_cfg["format"] = str(export_cfg.get("format", "PNG")).upper()
    export_cfg["quality"] = _validate_int(export_cfg.get("quality", 95), "export.quality", 1, 100)

    sensitive_cfg = config["sensitive_check"]
    sensitive_cfg["enable"] = False
    sensitive_cfg["backend"] = str(sensitive_cfg.get("backend", "tesseract"))
    sensitive_cfg["keywords"] = [str(item) for item in sensitive_cfg.get("keywords", []) if str(item).strip()]
    sensitive_cfg["case_sensitive"] = _validate_bool(sensitive_cfg.get("case_sensitive", True))
    sensitive_cfg["mode"] = str(sensitive_cfg.get("mode", "warn")).lower()
    sensitive_cfg["max_attempts"] = _validate_int(sensitive_cfg.get("max_attempts", 1), "sensitive_check.max_attempts", 1, 50)
    if sensitive_cfg["mode"] not in {"warn", "retry"}:
        raise ValidationError("sensitive_check.mode 只能是 warn 或 retry。")

    return config


def sanitize_device_config(device_config: dict[str, Any] | None, *, device_profile: str) -> dict[str, Any]:
    defaults = build_default_desktop_config() if device_profile == "desktop" else build_default_mobile_config()
    config = _clone(defaults)
    deep_merge(config, _clone(device_config or {}))

    canvas_cfg = config["canvas"]
    canvas_cfg["width"] = _validate_int(canvas_cfg.get("width", defaults["canvas"]["width"]), f"{device_profile}.canvas.width", 120, 600)
    canvas_cfg["height"] = _validate_int(canvas_cfg.get("height", defaults["canvas"]["height"]), f"{device_profile}.canvas.height", 120, 200000)
    canvas_cfg["margin"] = _validate_int(canvas_cfg.get("margin", defaults["canvas"]["margin"]), f"{device_profile}.canvas.margin", 0, 200)
    canvas_cfg["supersample"] = _validate_int(canvas_cfg.get("supersample", defaults["canvas"]["supersample"]), f"{device_profile}.canvas.supersample", 1, 4)

    layout_cfg = config["layout"]
    layout_cfg["max_chars_per_line"] = _validate_int(layout_cfg.get("max_chars_per_line", defaults["layout"]["max_chars_per_line"]), f"{device_profile}.layout.max_chars_per_line", 1, 200)
    layout_cfg["line_height_multiplier"] = _validate_float(layout_cfg.get("line_height_multiplier", defaults["layout"]["line_height_multiplier"]), f"{device_profile}.layout.line_height_multiplier", 0.5, 5.0)
    layout_cfg["micro_kerning_jitter"] = _validate_float(layout_cfg.get("micro_kerning_jitter", defaults["layout"]["micro_kerning_jitter"]), f"{device_profile}.layout.micro_kerning_jitter", 0.0, 10.0)
    layout_cfg["baseline_jitter"] = _validate_float(layout_cfg.get("baseline_jitter", defaults["layout"]["baseline_jitter"]), f"{device_profile}.layout.baseline_jitter", 0.0, 10.0)
    layout_cfg["character_scale_jitter"] = _validate_float(layout_cfg.get("character_scale_jitter", defaults["layout"]["character_scale_jitter"]), f"{device_profile}.layout.character_scale_jitter", 0.0, 1.0)

    font_cfg = config["font"]
    font_cfg["min_size"] = _validate_int(font_cfg.get("min_size", defaults["font"]["min_size"]), f"{device_profile}.font.min_size", 8, 256)
    font_cfg["max_size"] = _validate_int(font_cfg.get("max_size", defaults["font"]["max_size"]), f"{device_profile}.font.max_size", 8, 256)
    if font_cfg["min_size"] > font_cfg["max_size"]:
        raise ValidationError(f"{device_profile}.font.min_size 不可大於 {device_profile}.font.max_size。")

    background_cfg = config["background"]
    background_cfg["density"] = _validate_float(background_cfg.get("density", defaults["background"]["density"]), f"{device_profile}.background.density", 0.0, 1.0)

    return config


def validate_preset_configs(
    shared_config: dict[str, Any] | None,
    desktop_config: dict[str, Any] | None,
    mobile_config: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    shared = sanitize_shared_config(shared_config)
    desktop = sanitize_device_config(desktop_config, device_profile="desktop")
    mobile = sanitize_device_config(mobile_config, device_profile="mobile")
    return shared, desktop, mobile


def build_snapshot(
    *,
    base_preset_name: str,
    shared_config: dict[str, Any] | None,
    desktop_config: dict[str, Any] | None,
    mobile_config: dict[str, Any] | None,
) -> dict[str, Any]:
    shared, desktop, mobile = validate_preset_configs(shared_config, desktop_config, mobile_config)
    return {
        "engine": ANTI7OCR_ENGINE_NAME,
        "engine_commit": ANTI7OCR_ENGINE_COMMIT,
        "config_version": ANTI7OCR_CONFIG_VERSION,
        "base_preset_name": base_preset_name or DEFAULT_BASE_PRESET_NAME,
        "shared_config": shared,
        "desktop_config": desktop,
        "mobile_config": mobile,
    }


def legacy_snapshot_to_new(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = snapshot or {}
    desktop = snapshot.get("desktop", {})
    mobile = snapshot.get("mobile", {})
    shared = build_default_shared_config()
    shared["text"]["char_to_pinyin_ratio"] = float(snapshot.get("char_to_pinyin_ratio", 0.0) or 0.0)
    shared["text"]["enable_char_to_pinyin"] = shared["text"]["char_to_pinyin_ratio"] > 0
    shared["text"]["char_reverse_ratio"] = float(snapshot.get("char_reverse_ratio", 0.0) or 0.0)
    shared["text"]["enable_char_reverse"] = shared["text"]["char_reverse_ratio"] > 0

    desktop_config = build_default_desktop_config()
    desktop_config["canvas"]["width"] = int(desktop.get("width", desktop_config["canvas"]["width"]))
    desktop_config["font"]["min_size"] = int(desktop.get("min_font_size", desktop_config["font"]["min_size"]))
    desktop_config["font"]["max_size"] = int(desktop.get("max_font_size", desktop_config["font"]["max_size"]))
    desktop_config["background"]["density"] = float(desktop.get("bg_density", desktop_config["background"]["density"]))

    mobile_config = build_default_mobile_config()
    mobile_config["canvas"]["width"] = int(mobile.get("width", mobile_config["canvas"]["width"]))
    mobile_config["font"]["min_size"] = int(mobile.get("min_font_size", mobile_config["font"]["min_size"]))
    mobile_config["font"]["max_size"] = int(mobile.get("max_font_size", mobile_config["font"]["max_size"]))
    mobile_config["background"]["density"] = float(mobile.get("bg_density", mobile_config["background"]["density"]))

    return build_snapshot(
        base_preset_name=DEFAULT_BASE_PRESET_NAME,
        shared_config=shared,
        desktop_config=desktop_config,
        mobile_config=mobile_config,
    )


def normalize_preset_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = snapshot or {}
    if snapshot.get("engine") == ANTI7OCR_ENGINE_NAME and "shared_config" in snapshot:
        return build_snapshot(
            base_preset_name=str(snapshot.get("base_preset_name") or DEFAULT_BASE_PRESET_NAME),
            shared_config=snapshot.get("shared_config") or {},
            desktop_config=snapshot.get("desktop_config") or {},
            mobile_config=snapshot.get("mobile_config") or {},
        )
    return legacy_snapshot_to_new(snapshot)


def build_runtime_config(
    snapshot: dict[str, Any] | None,
    device_profile: str,
    *,
    enable_sensitive_check: bool = False,
    sensitive_keywords: list[str] | None = None,
    sensitive_mode: str = "warn",
    sensitive_max_attempts: int = 1,
) -> dict[str, Any]:
    normalized = normalize_preset_snapshot(snapshot)
    config = build_preset(normalized["base_preset_name"])
    deep_merge(config, _clone(normalized["shared_config"]))
    device_key = "desktop_config" if device_profile == "desktop" else "mobile_config"
    deep_merge(config, _clone(normalized[device_key]))

    from library.services.font_library import list_runtime_font_paths

    config.setdefault("font", {})
    config["font"]["paths"] = list_runtime_font_paths()
    config["font"]["directories"] = []
    config["font"]["fallback_to_default"] = True

    config.setdefault("canvas", {})
    # Keep output paper tone aligned with reader UI (rgba(255,250,242,0.95) on white ~= rgb(255,250,243)).
    config["canvas"]["background_color"] = list(DEFAULT_CANVAS_BACKGROUND_COLOR)

    config.setdefault("export", {})
    config["export"]["format"] = "PNG"

    config.setdefault("sensitive_check", {})
    config["sensitive_check"]["enable"] = bool(enable_sensitive_check)
    config["sensitive_check"]["backend"] = "tesseract"
    config["sensitive_check"]["keywords"] = list(sensitive_keywords or [])
    config["sensitive_check"]["case_sensitive"] = True
    config["sensitive_check"]["mode"] = sensitive_mode
    config["sensitive_check"]["max_attempts"] = sensitive_max_attempts
    if not enable_sensitive_check:
        config["sensitive_check"]["keywords"] = []
        config["sensitive_check"]["mode"] = "warn"
        config["sensitive_check"]["max_attempts"] = 1

    return config


def summarize_preset(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_preset_snapshot(snapshot)
    shared = normalized["shared_config"]
    desktop = normalized["desktop_config"]
    mobile = normalized["mobile_config"]
    return {
        "base_preset_name": normalized["base_preset_name"],
        "pinyin_enabled": bool(shared["text"].get("enable_char_to_pinyin")),
        "pinyin_ratio": shared["text"].get("char_to_pinyin_ratio", 0.0),
        "reverse_enabled": bool(shared["text"].get("enable_char_reverse")),
        "reverse_ratio": shared["text"].get("char_reverse_ratio", 0.0),
        "desktop_width": desktop["canvas"]["width"],
        "desktop_font_range": f'{desktop["font"]["min_size"]}-{desktop["font"]["max_size"]}',
        "mobile_width": mobile["canvas"]["width"],
        "mobile_font_range": f'{mobile["font"]["min_size"]}-{mobile["font"]["max_size"]}',
    }
