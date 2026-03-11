"""Static backend for testing and dry-run workflows."""

from __future__ import annotations

from PIL import Image

from .base import OCRBackend


class StaticBackend(OCRBackend):
    name = "static"

    def __init__(self, text: str = ""):
        self.text = text

    def recognize(self, image: Image.Image) -> str:
        _ = image  # Explicitly unused.
        return self.text

