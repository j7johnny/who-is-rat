"""Core data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image


@dataclass
class GlyphToken:
    """Token generated during layout."""

    char: str
    reverse: bool = False
    line_index: int = 0
    kerning_jitter: float = 0.0
    baseline_jitter: float = 0.0
    scale_jitter: float = 0.0
    rotation: float = 0.0


@dataclass
class GlyphRenderMeta:
    """Runtime metadata for rendered glyphs."""

    char: str
    bbox: tuple[int, int, int, int]
    line_index: int
    font_size: int
    reverse: bool = False


@dataclass
class LayoutResult:
    """Output of the layout stage."""

    tokens: list[GlyphToken] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


@dataclass
class RenderResult:
    """Output of the render stage."""

    image: Image.Image
    glyphs: list[GlyphRenderMeta] = field(default_factory=list)


@dataclass
class GenerationResult:
    """Returned by the public generate API."""

    image: Image.Image
    seed: int
    output_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchItemResult:
    """Single batch generation output."""

    item_id: str
    text: str
    seed: int
    output_path: Path | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchResult:
    """Batch generation output."""

    items: list[BatchItemResult]
    manifest_path: Path | None = None


@dataclass
class EvalSampleResult:
    """Recognition result for a single sample."""

    sample_id: str
    ground_truth: str
    recognized: dict[str, str]
    cer: dict[str, float]
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class EvalReport:
    """Aggregate OCR evaluation output."""

    samples: list[EvalSampleResult]
    avg_cer: dict[str, float]
