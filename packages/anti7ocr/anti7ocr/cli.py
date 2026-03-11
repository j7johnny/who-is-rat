"""Command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import click

from .api import evaluate, generate, generate_batch
from .font_manager import FontManager
from .presets import build_preset, preset_names


@click.group()
def cli():
    """anti7ocr CLI."""


@cli.command("generate")
@click.option("--text", type=str, default=None, help="Input text.")
@click.option("--text-file", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--preset", type=str, default=None)
@click.option("--seed", type=int, default=None)
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--format", "output_format", type=click.Choice(["PNG", "JPEG", "WEBP"]), default="PNG")
@click.option("--sensitive-check/--no-sensitive-check", default=None)
@click.option("--sensitive-keyword", "sensitive_keywords", multiple=True)
@click.option("--sensitive-mode", type=click.Choice(["warn", "retry"]), default=None)
@click.option("--sensitive-max-attempts", type=int, default=None)
@click.option("--sensitive-backend", type=str, default=None)
def generate_cmd(
    text,
    text_file,
    config_path,
    preset,
    seed,
    output,
    output_format,
    sensitive_check,
    sensitive_keywords,
    sensitive_mode,
    sensitive_max_attempts,
    sensitive_backend,
):
    """Generate a single image."""

    if not text and not text_file:
        raise click.UsageError("Either --text or --text-file must be provided.")
    if text_file:
        text = text_file.read_text(encoding="utf-8")
    config_override = _build_sensitive_override(
        enable=sensitive_check,
        keywords=sensitive_keywords,
        mode=sensitive_mode,
        max_attempts=sensitive_max_attempts,
        backend=sensitive_backend,
    )
    result = generate(
        text=text,
        config=config_override,
        preset=preset,
        config_path=config_path,
        seed=seed,
        output_options={"path": output, "format": output_format},
    )
    _echo_json({"seed": result.seed, "output_path": str(result.output_path)})


@cli.command("batch")
@click.option("--input-file", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--preset", type=str, default=None)
@click.option("--base-seed", type=int, default=None)
@click.option("--seed-strategy", type=click.Choice(["incremental", "random"]), default="incremental")
@click.option("--output-dir", type=click.Path(path_type=Path), default=Path("outputs"))
@click.option("--format", "output_format", type=click.Choice(["PNG", "JPEG", "WEBP"]), default="PNG")
@click.option("--sensitive-check/--no-sensitive-check", default=None)
@click.option("--sensitive-keyword", "sensitive_keywords", multiple=True)
@click.option("--sensitive-mode", type=click.Choice(["warn", "retry"]), default=None)
@click.option("--sensitive-max-attempts", type=int, default=None)
@click.option("--sensitive-backend", type=str, default=None)
def batch_cmd(
    input_file,
    config_path,
    preset,
    base_seed,
    seed_strategy,
    output_dir,
    output_format,
    sensitive_check,
    sensitive_keywords,
    sensitive_mode,
    sensitive_max_attempts,
    sensitive_backend,
):
    """Generate images in batch."""

    config_override = _build_sensitive_override(
        enable=sensitive_check,
        keywords=sensitive_keywords,
        mode=sensitive_mode,
        max_attempts=sensitive_max_attempts,
        backend=sensitive_backend,
    )
    result = generate_batch(
        input_source=input_file,
        config=config_override,
        preset=preset,
        config_path=config_path,
        base_seed=base_seed,
        seed_strategy=seed_strategy,
        output_dir=output_dir,
        output_format=output_format,
    )
    click.echo(
        _as_json(
            {"items": len(result.items), "manifest_path": str(result.manifest_path)},
        )
    )


@cli.command("eval")
@click.option("--manifest", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--backend", "backends", multiple=True, default=("tesseract",))
@click.option("--report", "report_path_opt", type=click.Path(path_type=Path), default=None)
def eval_cmd(manifest, backends, report_path_opt):
    """Evaluate OCR CER from a manifest jsonl."""

    images: list[Path] = []
    texts: list[str] = []
    with manifest.open("r", encoding="utf-8") as file:
        for line in file:
            item = json.loads(line)
            output_path = item.get("output_path")
            if not output_path:
                continue
            images.append(Path(output_path))
            texts.append(item.get("text", ""))
    eval_report = evaluate(images, texts, backends=list(backends))
    payload = {
        "avg_cer": eval_report.avg_cer,
        "sample_count": len(eval_report.samples),
        "samples": [
            {
                "sample_id": item.sample_id,
                "ground_truth": item.ground_truth,
                "recognized": item.recognized,
                "cer": item.cer,
                "errors": item.errors,
            }
            for item in eval_report.samples
        ],
    }
    if report_path_opt is not None:
        report_path = Path(report_path_opt).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(report_path)
    _echo_json(payload)


@cli.group("preset")
def preset_group():
    """Inspect built-in presets."""


@preset_group.command("list")
def preset_list():
    _echo_json({"presets": preset_names()})


@preset_group.command("show")
@click.argument("name")
def preset_show(name):
    config = build_preset(name)
    _echo_json(config, indent=2)


@cli.command("font-check")
@click.option("--text", type=str, required=True)
@click.option("--font-path", "font_paths", multiple=True)
@click.option("--font-dir", "font_dirs", multiple=True)
@click.option("--size", type=int, default=24)
def font_check_cmd(text, font_paths, font_dirs, size):
    """Check glyph coverage for text against configured fonts."""

    manager = FontManager(paths=font_paths, directories=font_dirs, fallback_to_default=True)
    report = manager.inspect_text_coverage(text, size=size)
    _echo_json(report)


def _build_sensitive_override(*, enable, keywords, mode, max_attempts, backend):
    has_override = any(
        [
            enable is not None,
            bool(keywords),
            mode is not None,
            max_attempts is not None,
            backend is not None,
        ]
    )
    if not has_override:
        return {}
    cfg = {"sensitive_check": {}}
    if enable is not None:
        cfg["sensitive_check"]["enable"] = bool(enable)
    if keywords:
        cfg["sensitive_check"]["keywords"] = [str(item) for item in keywords]
    if mode is not None:
        cfg["sensitive_check"]["mode"] = str(mode)
    if max_attempts is not None:
        cfg["sensitive_check"]["max_attempts"] = int(max_attempts)
    if backend is not None:
        cfg["sensitive_check"]["backend"] = str(backend)
    return cfg


def _as_json(payload, *, indent=None):
    return json.dumps(payload, ensure_ascii=False, indent=indent)


def _echo_json(payload, *, indent=None):
    text = _as_json(payload, indent=indent)
    try:
        click.echo(text)
    except UnicodeEncodeError:
        click.echo(json.dumps(payload, ensure_ascii=True, indent=indent))
