from datetime import date

from django.conf import settings
from django.core import signing
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

signer = signing.TimestampSigner(salt="reader-page")


def build_signed_page_key(version_id: int, reader_id: str, for_date: date, device_profile: str) -> str:
    raw = f"{version_id}|{reader_id}|{for_date:%Y%m%d}|{device_profile}"
    signed = signer.sign(raw)
    return urlsafe_base64_encode(signed.encode("utf-8"))


def parse_signed_page_key(signed_key: str) -> tuple[int, str, date, str]:
    decoded = urlsafe_base64_decode(signed_key).decode("utf-8")
    value = signer.unsign(decoded, max_age=settings.READER_IMAGE_TOKEN_MAX_AGE)
    version_id, reader_id, yyyymmdd, device_profile = value.split("|", 3)
    date_value = date.fromisoformat(f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}")
    return int(version_id), reader_id, date_value, device_profile
