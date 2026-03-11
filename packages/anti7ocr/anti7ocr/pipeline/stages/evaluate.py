"""Evaluate stage hook."""

from __future__ import annotations


class EvaluateStage:
    """Optional stage hook. Runs only when evaluation callback exists."""

    name = "evaluate"

    def __call__(self, ctx):
        callback = ctx.metadata.get("evaluate_callback")
        if callback is None or ctx.image is None:
            return ctx
        ctx.metadata["evaluation"] = callback(ctx.image)
        return ctx

