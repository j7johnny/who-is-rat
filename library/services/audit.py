from library.models import AuditLog


def log_event(event_type: str, user=None, request=None, details: dict | None = None) -> AuditLog:
    ip_address = None
    if request is not None:
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else request.META.get("REMOTE_ADDR")
    return AuditLog.objects.create(
        user=user,
        event_type=event_type,
        ip_address=ip_address,
        details=details or {},
    )
