"""Built-in configuration presets."""

from __future__ import annotations

from copy import deepcopy

from .constants import DEFAULT_PRESET_NAME


DEFAULT_CONFIG: dict = {
    "text": {
        "unicode_normalization": "NFC",
        "enable_char_to_pinyin": True,
        "char_to_pinyin_ratio": 0.10,
        "enable_char_reverse": True,
        "char_reverse_ratio": 0.10,
        "reverse_rotation_range": [170, 190],
    },
    "canvas": {
        "width": 1280,
        "height": 720,
        "margin": 24,
        "background_color": [255, 255, 255],
        "text_color": [20, 20, 20],
        "supersample": 2,
        "dpi": 96,
    },
    "layout": {
        "max_chars_per_line": 36,
        "line_height_multiplier": 1.35,
        "micro_kerning_jitter": 1.25,
        "baseline_jitter": 1.50,
        "character_scale_jitter": 0.08,
    },
    "font": {
        "paths": [],
        "directories": [],
        "fallback_to_default": True,
        "min_size": 28,
        "max_size": 46,
    },
    "background": {
        "enable": True,
        "density": 0.15,
        "min_font_size": 10,
        "max_font_size": 24,
        "foreground": [130, 130, 130],
    },
    "fragment": {
        "enable": True,
        "stroke_fragmentation_prob": 0.28,
        "closed_structure_break_prob": 0.30,
        "closed_structure_chars": "口日目田國囗回園圖器品問間門閩",
        "erase_width": 2,
        "erase_ratio": 0.08,
        "max_stroke_fragments": 2,
        "max_closed_breaks": 1,
    },
    "perturb": {
        "enable": True,
        "edge_jitter_strength": 0.07,
        "edge_brightness_noise": 16,
        "local_contrast_noise": 0.15,
        "local_contrast_patches": 18,
        "adversarial_watermark_enable": True,
        "watermark_text": "anti7ocr",
        "watermark_opacity": 22,
        "watermark_density": 0.16,
        "watermark_scale": 0.60,
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


PRESETS: dict[str, dict] = {
    "tw_readable": {
        "text": {"char_to_pinyin_ratio": 0.08, "char_reverse_ratio": 0.08},
        "fragment": {"stroke_fragmentation_prob": 0.18, "closed_structure_break_prob": 0.20},
        "perturb": {
            "edge_jitter_strength": 0.05,
            "edge_brightness_noise": 10,
            "local_contrast_noise": 0.10,
            "watermark_opacity": 16,
        },
    },
    "tw_balanced": {
        "text": {"char_to_pinyin_ratio": 0.10, "char_reverse_ratio": 0.12},
        "layout": {
            "micro_kerning_jitter": 1.5,
            "baseline_jitter": 1.6,
            "character_scale_jitter": 0.10,
        },
        "fragment": {
            "stroke_fragmentation_prob": 0.24,
            "closed_structure_break_prob": 0.26,
            "max_stroke_fragments": 2,
            "max_closed_breaks": 1,
        },
        "perturb": {
            "edge_jitter_strength": 0.08,
            "edge_brightness_noise": 14,
            "local_contrast_noise": 0.16,
            "local_contrast_patches": 20,
            "watermark_opacity": 20,
        },
    },
    "tw_aggressive": {
        "text": {"char_to_pinyin_ratio": 0.14, "char_reverse_ratio": 0.16},
        "fragment": {"stroke_fragmentation_prob": 0.35, "closed_structure_break_prob": 0.36},
        "perturb": {
            "edge_jitter_strength": 0.12,
            "edge_brightness_noise": 26,
            "local_contrast_noise": 0.25,
            "watermark_opacity": 28,
        },
    },
    "tw_hardened": {
        "text": {"char_to_pinyin_ratio": 0.18, "char_reverse_ratio": 0.20},
        "layout": {
            "micro_kerning_jitter": 2.2,
            "baseline_jitter": 2.2,
            "character_scale_jitter": 0.14,
        },
        "background": {"density": 0.22},
        "fragment": {
            "stroke_fragmentation_prob": 0.40,
            "closed_structure_break_prob": 0.44,
            "erase_ratio": 0.10,
            "max_stroke_fragments": 3,
            "max_closed_breaks": 2,
        },
        "perturb": {
            "edge_jitter_strength": 0.15,
            "edge_brightness_noise": 30,
            "local_contrast_noise": 0.30,
            "local_contrast_patches": 24,
            "watermark_opacity": 34,
            "watermark_density": 0.22,
            "watermark_scale": 0.75,
        },
    },
}


def preset_names() -> list[str]:
    return sorted(PRESETS.keys())


def build_preset(name: str | None) -> dict:
    resolved = name or DEFAULT_PRESET_NAME
    merged = deepcopy(DEFAULT_CONFIG)
    if resolved in PRESETS:
        _deep_merge(merged, deepcopy(PRESETS[resolved]))
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
