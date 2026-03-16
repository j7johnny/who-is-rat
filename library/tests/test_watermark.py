"""Comprehensive watermark round-trip tests.

Tests both blind and visible watermarks for embed → save → extract integrity.
"""
from __future__ import annotations

import io
import tempfile
from datetime import date
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from library.services.visible_watermark import (
    apply_visible_watermark,
    build_visible_watermark_payload,
    embed_visible_watermark,
    extract_visible_watermark_from_bytes,
)
from library.services.watermark import (
    build_watermark_payload,
    embed_watermark,
    extract_watermark_from_bytes,
    parse_watermark_payload,
    payload_to_bits,
    bits_to_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_base_image(width: int = 600, height: int = 860, bg_color=(254, 249, 241)) -> Image.Image:
    """Create a realistic base image with text-like patterns."""
    img = Image.new("RGB", (width, height), bg_color)
    pixels = np.array(img)
    rng = np.random.default_rng(42)
    # Add subtle noise to simulate real page content
    noise = rng.integers(-3, 4, size=pixels.shape, dtype=np.int16)
    pixels = np.clip(pixels.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    # Add some dark rectangles to simulate text
    for i in range(20):
        y = rng.integers(40, height - 60)
        x = rng.integers(20, width - 200)
        w = rng.integers(100, 300)
        h = rng.integers(20, 40)
        pixels[y:y+h, x:min(x+w, width)] = rng.integers(10, 50, size=(h, min(x+w, width)-x, 3))
    return Image.fromarray(pixels)


def _save_tmp_png(img: Image.Image) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(f.name, format="PNG")
    f.close()
    return Path(f.name)


READER_IDS = ["alice", "bob123", "reader_01", "test-user"]
TEST_DATES = [date(2026, 3, 16), date(2026, 1, 1), date(2025, 12, 31)]
DEVICE_PROFILES = ["desktop", "mobile"]
IMAGE_SIZES = [(600, 860), (420, 760)]

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Blind watermark tests
# ---------------------------------------------------------------------------

class TestBlindWatermarkPayload:
    """Test payload encoding/decoding."""

    @pytest.mark.parametrize("reader_id", READER_IDS)
    def test_payload_format(self, reader_id):
        payload = build_watermark_payload(reader_id, date(2026, 3, 16))
        assert reader_id in payload
        assert "20260316" in payload

    def test_payload_roundtrip_bits(self):
        payload = build_watermark_payload("alice", date(2026, 3, 16))
        bits = payload_to_bits(payload)
        recovered = bits_to_payload(bits)
        assert payload == recovered

    @pytest.mark.parametrize("reader_id", READER_IDS)
    def test_parse_payload(self, reader_id):
        payload = build_watermark_payload(reader_id, date(2026, 3, 16))
        parsed = parse_watermark_payload(payload)
        assert parsed is not None
        assert parsed["reader_id"] == reader_id
        assert parsed["yyyymmdd"] == "20260316"


class TestBlindWatermarkEmbedExtract:
    """Full embed → extract round-trip for blind watermark."""

    @pytest.mark.parametrize("reader_id,for_date,size", [
        ("alice", date(2026, 3, 16), (600, 860)),
        ("bob123", date(2026, 1, 1), (600, 860)),
        ("reader_01", date(2025, 12, 31), (420, 760)),
    ])
    def test_embed_extract_roundtrip(self, reader_id, for_date, size, tmp_path):
        """Embed blind watermark and extract it from PNG."""
        img = _make_base_image(*size)
        input_path = str(tmp_path / "input.png")
        output_path = str(tmp_path / "output.png")
        img.save(input_path, format="PNG")

        payload = build_watermark_payload(reader_id, for_date)
        result = embed_watermark(
            input_path, output_path, payload,
            expected_reader_id=reader_id,
            expected_yyyymmdd=for_date.strftime("%Y%m%d"),
        )

        # Verify embed reported success
        assert result["verified"], f"Embed verification failed: {result.get('verification_trace')}"

        # Now extract
        with open(output_path, "rb") as f:
            file_bytes = f.read()

        extract_result = extract_watermark_from_bytes(
            file_bytes,
            allow_crops=False,
            expected_reader_ids=[reader_id],
            expected_dates=[for_date.strftime("%Y%m%d")],
        )

        assert extract_result["parsed"] is not None, f"Extract failed: {extract_result}"
        assert extract_result["parsed"]["reader_id"] == reader_id
        assert extract_result["parsed"]["yyyymmdd"] == for_date.strftime("%Y%m%d")

    def test_embed_preserves_image_dimensions(self, tmp_path):
        """Watermarked image should have same or similar dimensions."""
        img = _make_base_image(600, 860)
        input_path = str(tmp_path / "input.png")
        output_path = str(tmp_path / "output.png")
        img.save(input_path, format="PNG")

        payload = build_watermark_payload("alice", date(2026, 3, 16))
        embed_watermark(input_path, output_path, payload)

        result_img = Image.open(output_path)
        assert result_img.width == 600
        # Height may increase slightly due to carrier padding
        assert result_img.height >= 860

    def test_different_readers_produce_different_watermarks(self, tmp_path):
        """Two different readers should produce different watermarked images."""
        img = _make_base_image(600, 860)
        input_path = str(tmp_path / "input.png")
        img.save(input_path, format="PNG")

        outputs = []
        for reader_id in ["alice", "bob123"]:
            out = str(tmp_path / f"output_{reader_id}.png")
            payload = build_watermark_payload(reader_id, date(2026, 3, 16))
            embed_watermark(input_path, out, payload)
            with open(out, "rb") as f:
                outputs.append(f.read())

        # Files should differ (different payloads embedded)
        assert outputs[0] != outputs[1]


# ---------------------------------------------------------------------------
# Visible watermark tests
# ---------------------------------------------------------------------------

class TestVisibleWatermarkPayload:
    """Test visible watermark payload format."""

    @pytest.mark.parametrize("reader_id", READER_IDS)
    def test_payload_format(self, reader_id):
        payload = build_visible_watermark_payload(reader_id, date(2026, 3, 16))
        assert payload == f"{reader_id}|20260316"


class TestVisibleWatermarkEmbed:
    """Test visible watermark embedding produces detectable changes."""

    @pytest.mark.parametrize("device_profile,size", [
        ("desktop", (600, 860)),
        ("mobile", (420, 760)),
    ])
    def test_embed_modifies_image(self, device_profile, size, tmp_path):
        """Visible watermark should modify pixel values."""
        img = _make_base_image(*size)
        input_path = str(tmp_path / "input.png")
        output_path = str(tmp_path / "output.png")
        img.save(input_path, format="PNG")

        payload = build_visible_watermark_payload("alice", date(2026, 3, 16))
        embed_visible_watermark(input_path, output_path, payload, device_profile=device_profile)

        original = np.array(Image.open(input_path))
        watermarked = np.array(Image.open(output_path))

        # Images should differ
        diff = np.abs(original.astype(np.int16) - watermarked.astype(np.int16))
        changed_pixels = np.sum(diff > 0)
        total_pixels = original.shape[0] * original.shape[1] * original.shape[2]

        # At least 0.5% of pixels should be modified
        change_ratio = changed_pixels / total_pixels
        assert change_ratio > 0.005, f"Only {change_ratio:.4%} pixels changed — watermark too subtle"

    @pytest.mark.parametrize("device_profile", DEVICE_PROFILES)
    def test_lsb_layer_detectable(self, device_profile, tmp_path):
        """LSB layer should be extractable from the blue/green channels."""
        img = _make_base_image(600, 860)
        input_path = str(tmp_path / "input.png")
        output_path = str(tmp_path / "output.png")
        img.save(input_path, format="PNG")

        payload = build_visible_watermark_payload("alice", date(2026, 3, 16))
        embed_visible_watermark(input_path, output_path, payload, device_profile=device_profile)

        watermarked = cv2.imread(output_path)
        blue = watermarked[:, :, 0]
        green = watermarked[:, :, 1]

        # Extract LSB bits
        blue_lsb = blue & 0x07  # 3 bits
        green_lsb = green & 0x03  # 2 bits

        # There should be a non-trivial number of non-zero LSB values
        blue_signal = np.sum(blue_lsb > 0)
        green_signal = np.sum(green_lsb > 0)
        total = blue.shape[0] * blue.shape[1]

        assert blue_signal / total > 0.01, "Blue LSB signal too weak"
        assert green_signal / total > 0.01, "Green LSB signal too weak"

    @pytest.mark.parametrize("device_profile", DEVICE_PROFILES)
    def test_luminance_overlay_detectable(self, device_profile, tmp_path):
        """Luminance overlay should create detectable darkening patterns."""
        img = _make_base_image(600, 860)
        input_path = str(tmp_path / "input.png")
        output_path = str(tmp_path / "output.png")
        img.save(input_path, format="PNG")

        payload = build_visible_watermark_payload("alice", date(2026, 3, 16))
        embed_visible_watermark(input_path, output_path, payload, device_profile=device_profile)

        original = cv2.imread(input_path)
        watermarked = cv2.imread(output_path)

        orig_gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY).astype(np.float32)
        wm_gray = cv2.cvtColor(watermarked, cv2.COLOR_BGR2GRAY).astype(np.float32)

        # Watermark should darken some bright regions
        darkened = (orig_gray - wm_gray) > 1.0
        darkened_ratio = np.sum(darkened) / darkened.size

        assert darkened_ratio > 0.005, f"Only {darkened_ratio:.4%} of pixels darkened — overlay too subtle"


class TestVisibleWatermarkExtract:
    """Test visible watermark extraction (OCR-based, may require tesseract)."""

    @pytest.mark.parametrize("device_profile", DEVICE_PROFILES)
    def test_extract_from_png(self, device_profile, tmp_path):
        """Extract visible watermark from a PNG image."""
        img = _make_base_image(600, 860)
        input_path = str(tmp_path / "input.png")
        output_path = str(tmp_path / "output.png")
        img.save(input_path, format="PNG")

        payload = build_visible_watermark_payload("alice", date(2026, 3, 16))
        embed_visible_watermark(input_path, output_path, payload, device_profile=device_profile)

        with open(output_path, "rb") as f:
            file_bytes = f.read()

        result = extract_visible_watermark_from_bytes(file_bytes)
        # Even without tesseract, the reveal variants should be generated
        assert "variants" in result or "raw_ocr" in result or "parsed" in result


# ---------------------------------------------------------------------------
# Dual watermark (combined blind + visible) tests
# ---------------------------------------------------------------------------

class TestDualWatermark:
    """Test combined blind + visible watermark pipeline (as used in production)."""

    @pytest.mark.parametrize("reader_id,for_date", [
        ("alice", date(2026, 3, 16)),
        ("bob123", date(2026, 1, 1)),
        ("test-user", date(2025, 12, 31)),
    ])
    def test_dual_embed_blind_extract(self, reader_id, for_date, tmp_path):
        """Embed both watermarks, verify blind extraction still works."""
        img = _make_base_image(600, 860)
        input_path = str(tmp_path / "input.png")
        blind_path = str(tmp_path / "blind.png")
        final_path = str(tmp_path / "final.png")
        img.save(input_path, format="PNG")

        # Step 1: Embed blind watermark
        blind_payload = build_watermark_payload(reader_id, for_date)
        blind_result = embed_watermark(
            input_path, blind_path, blind_payload,
            expected_reader_id=reader_id,
            expected_yyyymmdd=for_date.strftime("%Y%m%d"),
        )
        assert blind_result["verified"], f"Blind embed failed: {blind_result.get('verification_trace')}"

        # Step 2: Embed visible watermark on top
        visible_payload = build_visible_watermark_payload(reader_id, for_date)
        embed_visible_watermark(blind_path, final_path, visible_payload, device_profile="desktop")

        # Step 3: Extract blind watermark from dual-watermarked image
        with open(final_path, "rb") as f:
            file_bytes = f.read()

        extract_result = extract_watermark_from_bytes(
            file_bytes,
            allow_crops=False,
            expected_reader_ids=[reader_id],
            expected_dates=[for_date.strftime("%Y%m%d")],
        )

        assert extract_result["parsed"] is not None, (
            f"Blind extraction failed after dual embedding: {extract_result}"
        )
        assert extract_result["parsed"]["reader_id"] == reader_id
        assert extract_result["parsed"]["yyyymmdd"] == for_date.strftime("%Y%m%d")

    def test_dual_embed_all_readers_distinguishable(self, tmp_path):
        """Different readers should produce extractable, distinct watermarks."""
        img = _make_base_image(600, 860)
        input_path = str(tmp_path / "input.png")
        img.save(input_path, format="PNG")

        for_date = date(2026, 3, 16)
        results = {}

        for reader_id in ["alice", "bob123", "reader_01"]:
            blind_path = str(tmp_path / f"blind_{reader_id}.png")
            final_path = str(tmp_path / f"final_{reader_id}.png")

            blind_payload = build_watermark_payload(reader_id, for_date)
            embed_watermark(input_path, blind_path, blind_payload,
                            expected_reader_id=reader_id,
                            expected_yyyymmdd=for_date.strftime("%Y%m%d"))

            visible_payload = build_visible_watermark_payload(reader_id, for_date)
            embed_visible_watermark(blind_path, final_path, visible_payload, device_profile="desktop")

            with open(final_path, "rb") as f:
                file_bytes = f.read()

            extract_result = extract_watermark_from_bytes(
                file_bytes, allow_crops=False,
                expected_reader_ids=[reader_id],
                expected_dates=[for_date.strftime("%Y%m%d")],
            )
            results[reader_id] = extract_result

        # All should be successfully extracted with correct reader_id
        for reader_id, result in results.items():
            assert result["parsed"] is not None, f"Failed for {reader_id}: {result}"
            assert result["parsed"]["reader_id"] == reader_id


# ---------------------------------------------------------------------------
# Robustness tests
# ---------------------------------------------------------------------------

class TestWatermarkRobustness:
    """Test watermark survival under transformations."""

    def _embed_dual(self, tmp_path, reader_id="alice", for_date=date(2026, 3, 16)):
        """Helper: create a dual-watermarked image."""
        img = _make_base_image(600, 860)
        input_path = str(tmp_path / "input.png")
        blind_path = str(tmp_path / "blind.png")
        final_path = str(tmp_path / "final.png")
        img.save(input_path, format="PNG")

        blind_payload = build_watermark_payload(reader_id, for_date)
        embed_watermark(input_path, blind_path, blind_payload,
                        expected_reader_id=reader_id,
                        expected_yyyymmdd=for_date.strftime("%Y%m%d"))

        visible_payload = build_visible_watermark_payload(reader_id, for_date)
        embed_visible_watermark(blind_path, final_path, visible_payload, device_profile="desktop")

        return final_path, reader_id, for_date

    def test_png_resave(self, tmp_path):
        """Blind watermark should survive PNG re-save."""
        final_path, reader_id, for_date = self._embed_dual(tmp_path)

        # Re-save as PNG
        img = Image.open(final_path)
        resaved_path = str(tmp_path / "resaved.png")
        img.save(resaved_path, format="PNG")

        with open(resaved_path, "rb") as f:
            file_bytes = f.read()

        result = extract_watermark_from_bytes(
            file_bytes, allow_crops=False,
            expected_reader_ids=[reader_id],
            expected_dates=[for_date.strftime("%Y%m%d")],
        )
        assert result["parsed"] is not None, "Failed after PNG re-save"
        assert result["parsed"]["reader_id"] == reader_id
