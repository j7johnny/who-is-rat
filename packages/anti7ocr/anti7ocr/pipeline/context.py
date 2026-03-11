"""Pipeline context container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from ..models import LayoutResult, RenderResult


@dataclass
class PipelineContext:
    text: str
    config: dict
    py_rng: Any
    np_rng: np.random.Generator
    seed: int
    layout: LayoutResult | None = None
    render: RenderResult | None = None
    image: Image.Image | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

