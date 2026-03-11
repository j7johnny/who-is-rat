"""Base backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class OCRBackend(ABC):
    """Abstract OCR backend."""

    name = "base"

    @abstractmethod
    def recognize(self, image: Image.Image) -> str:
        raise NotImplementedError

