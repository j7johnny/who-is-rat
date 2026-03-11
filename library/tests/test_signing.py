"""Tests for signed URL token generation and validation."""
import time
from datetime import date

import pytest
from django.core import signing
from django.test import override_settings

from library.services.signing import build_signed_page_key, parse_signed_page_key


@pytest.mark.django_db
class TestSignedPageKey:
    def test_roundtrip(self):
        version_id = 42
        reader_id = "testuser"
        for_date = date(2026, 3, 11)
        device_profile = "desktop"

        key = build_signed_page_key(version_id, reader_id, for_date, device_profile)
        parsed = parse_signed_page_key(key)

        assert parsed == (42, "testuser", date(2026, 3, 11), "desktop")

    def test_mobile_device(self):
        key = build_signed_page_key(1, "reader01", date(2026, 1, 1), "mobile")
        v, r, d, dp = parse_signed_page_key(key)
        assert dp == "mobile"

    def test_tampered_key_raises(self):
        key = build_signed_page_key(1, "reader01", date(2026, 1, 1), "desktop")
        tampered = key[:-4] + "XXXX"
        with pytest.raises(Exception):
            parse_signed_page_key(tampered)

    def test_empty_key_raises(self):
        with pytest.raises(Exception):
            parse_signed_page_key("")

    @override_settings(READER_IMAGE_TOKEN_MAX_AGE=1)
    def test_expired_key_raises(self):
        key = build_signed_page_key(1, "reader01", date(2026, 1, 1), "desktop")
        time.sleep(1.5)
        with pytest.raises(signing.SignatureExpired):
            parse_signed_page_key(key)

    def test_different_readers_get_different_keys(self):
        d = date(2026, 3, 11)
        key1 = build_signed_page_key(1, "reader01", d, "desktop")
        key2 = build_signed_page_key(1, "reader02", d, "desktop")
        assert key1 != key2

    def test_different_dates_get_different_keys(self):
        key1 = build_signed_page_key(1, "reader01", date(2026, 3, 11), "desktop")
        key2 = build_signed_page_key(1, "reader01", date(2026, 3, 12), "desktop")
        assert key1 != key2
