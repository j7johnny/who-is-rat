"""Pipeline engine."""

from __future__ import annotations

from .context import PipelineContext
from .stages import EvaluateStage, ExportStage, FragmentStage, LayoutStage, PerturbStage, RenderStage


class PipelineEngine:
    """Sequential pipeline engine with configurable stages."""

    def __init__(self):
        self.stages = [
            LayoutStage(),
            RenderStage(),
            FragmentStage(),
            PerturbStage(),
            ExportStage(),
            EvaluateStage(),
        ]

    def run(self, ctx: PipelineContext) -> PipelineContext:
        for stage in self.stages:
            ctx = stage(ctx)
        return ctx

