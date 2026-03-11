"""Configuration loading and precedence handling."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .presets import build_preset, _deep_merge


def load_yaml_config(path: str | Path | None) -> dict:
    if path is None:
        return {}
    with Path(path).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML config must be a mapping object")
    return data


def resolve_config(
    *,
    preset: str | None = None,
    yaml_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict:
    """Resolve config with precedence: overrides > yaml > preset > defaults."""

    config = build_preset(preset)
    yaml_config = load_yaml_config(yaml_path)
    _deep_merge(config, deepcopy(yaml_config))
    _deep_merge(config, deepcopy(overrides or {}))
    return config

