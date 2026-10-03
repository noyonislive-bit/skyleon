from .models import AuditLog
from .ratelimit import client_ip


def log(request_or_user, action: str, obj=None, **meta):
    """Record an administrative action. Accepts a request or a user."""
    user = getattr(request_or_user, "user", request_or_user)
    ip = client_ip(request_or_user) if hasattr(request_or_user, "META") else None
    AuditLog.objects.create(
        actor=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        entity_type=obj._meta.model_name if obj is not None else "",
        entity_id=str(obj.pk) if obj is not None else "",
        meta=meta,
        ip_address=ip,
    )
