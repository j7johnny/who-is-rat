"""CnOCR backend adapter."""

from __future__ import annotations

from PIL import Image

from .base import OCRBackend


class CnOCRBackend(OCRBackend):
    name = "cnocr"

    def __init__(self):
        try:
            from cnocr import CnOcr  # type: ignore
        except ImportError as exc:
            raise RuntimeError("cnocr is not installed. Install anti7ocr with the 'eval' extra.") from exc
        self._model = CnOcr()

    def recognize(self, image: Image.Image) -> str:
        out = self._model.ocr(image.convert("RGB"))
        if not out:
            return ""
        texts = []
        for item in out:
            if isinstance(item, dict):
                texts.append(item.get("text", ""))
            elif isinstance(item, (list, tuple)) and item:
                texts.append(str(item[-1]))
        return "".join(texts).strip()

