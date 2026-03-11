from pathlib import Path


def read_version(base_dir: Path) -> str:
    version_file = base_dir / "VERSION"
    if not version_file.exists():
        return "v0.0.0"
    return version_file.read_text(encoding="utf-8").strip() or "v0.0.0"
