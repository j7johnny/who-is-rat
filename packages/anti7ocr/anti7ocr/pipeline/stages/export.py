"""Export stage."""

from __future__ import annotations

from pathlib import Path


class ExportStage:
    """Persist image output if destination is provided."""

    name = "export"

    def __call__(self, ctx):
        if ctx.image is None:
            raise RuntimeError("Image is missing before export stage")
        output_path = ctx.metadata.get("output_path")
        if not output_path:
            return ctx
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        export_cfg = ctx.config.get("export", {})
        image_format = str(export_cfg.get("format", "PNG")).upper()
        quality = int(export_cfg.get("quality", 95))
        save_kwargs = {}
        if image_format in {"JPEG", "JPG", "WEBP"}:
            save_kwargs["quality"] = quality
        image = ctx.image.convert("RGB") if image_format in {"JPEG", "JPG"} else ctx.image
        image.save(path, format=image_format, **save_kwargs)
        ctx.metadata["saved_path"] = str(path)
        return ctx

