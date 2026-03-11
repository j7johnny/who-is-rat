from django.conf import settings
from django.core.cache import cache

from library.models import AuditLog
from library.services.audit import log_event


def get_client_ip(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


def _safe_increment(key: str, timeout: int) -> int:
    cache.add(key, 0, timeout=timeout)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return 1


def get_login_lock_reason(username: str, ip_address: str) -> str | None:
    if cache.get(f"login-lock-account:{username}"):
        return "此帳號暫時鎖定，請稍後再試。"
    if cache.get(f"login-lock-ip:{username}:{ip_address}"):
        return "嘗試次數過多，請稍後再試。"
    return None


def record_login_failure(username: str, ip_address: str, request=None) -> None:
    window = settings.LOGIN_FAILURE_WINDOW_SECONDS
    ip_attempts = _safe_increment(f"login-fail-ip:{username}:{ip_address}", window)
    account_attempts = _safe_increment(f"login-fail-account:{username}", window)

    if ip_attempts >= 5:
        cache.set(
            f"login-lock-ip:{username}:{ip_address}",
            True,
            timeout=settings.LOGIN_FAILURE_COOLDOWN_SECONDS,
        )
    if account_attempts >= 10:
        cache.set(
            f"login-lock-account:{username}",
            True,
            timeout=settings.ACCOUNT_LOCK_SECONDS,
        )

    if request is not None:
        log_event(
            AuditLog.EventType.LOGIN_FAILURE,
            request=request,
            details={"username": username, "ip_attempts": ip_attempts, "account_attempts": account_attempts},
        )


def clear_login_failures(username: str, ip_address: str) -> None:
    cache.delete_many(
        [
            f"login-fail-ip:{username}:{ip_address}",
            f"login-fail-account:{username}",
            f"login-lock-ip:{username}:{ip_address}",
            f"login-lock-account:{username}",
        ]
    )
