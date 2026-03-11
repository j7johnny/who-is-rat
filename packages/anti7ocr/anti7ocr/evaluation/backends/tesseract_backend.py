"""Tesseract backend adapter."""

from __future__ import annotations

from PIL import Image

from .base import OCRBackend


class TesseractBackend(OCRBackend):
    name = "tesseract"

    def __init__(self, *, lang: str = "chi_tra+eng"):
        self.lang = lang
        try:
            import pytesseract  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pytesseract is not installed. Install anti7ocr with the 'eval' extra."
            ) from exc
        self._pytesseract = pytesseract

    def recognize(self, image: Image.Image) -> str:
        text = self._pytesseract.image_to_string(image.convert("RGB"), lang=self.lang)
        return text.strip()

