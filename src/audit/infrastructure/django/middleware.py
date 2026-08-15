from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .services import record_audit_event


class AuthenticationAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)


def _client_ip(request) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _request_metadata(request) -> dict[str, str]:
    return {
        "path": request.path,
        "method": request.method,
    }


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs) -> None:
    record_audit_event(
        action="login",
        actor=user,
        target=user,
        metadata=_request_metadata(request),
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        request_id=getattr(request, "request_id", ""),
    )


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs) -> None:
    record_audit_event(
        action="logout",
        actor=user,
        target=user,
        metadata=_request_metadata(request),
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        request_id=getattr(request, "request_id", ""),
    )


@receiver(user_login_failed)
def audit_login_failed(sender, credentials, request, **kwargs) -> None:
    record_audit_event(
        action="login_failed",
        metadata={"username": credentials.get("username", "")},
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        request_id=getattr(request, "request_id", ""),
    )
