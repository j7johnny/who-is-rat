from pathlib import Path

from django.conf import settings


def media_relative(*parts: str) -> str:
    return Path(*parts).as_posix()


def media_absolute(relative_path: str) -> Path:
    return Path(settings.MEDIA_ROOT) / relative_path


def ensure_parent(relative_path: str) -> Path:
    absolute_path = media_absolute(relative_path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    return absolute_path


def delete_relative_path(relative_path: str) -> None:
    path = media_absolute(relative_path)
    if path.exists():
        path.unlink()
