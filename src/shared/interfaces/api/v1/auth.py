from django.core import signing
from django.core.cache import cache
from django.http import JsonResponse
from functools import wraps
from django.contrib.auth import get_user_model

User = get_user_model()

SALT_ACCESS = "mobile-driver-access"
SALT_REFRESH = "mobile-driver-refresh"


def generate_access_token(user) -> str:
    """Generate a short-lived signed access token (15 minutes)."""
    return signing.dumps({"user_id": str(user.id), "token_type": "access"}, salt=SALT_ACCESS)


def generate_signed_token(user) -> str:
    """Compatibility wrapper returning an access token for a user.

    Existing tests import ``generate_signed_token``; this function
    simply forwards to :func:`generate_access_token`.
    """
    return generate_access_token(user)


def generate_refresh_token(user) -> str:
    """Generate a long-lived signed refresh token (30 days)."""
    return signing.dumps({"user_id": str(user.id), "token_type": "refresh"}, salt=SALT_REFRESH)


def is_token_revoked(token: str) -> bool:
    """Check if the given token signature/payload is blacklisted in cache."""
    return cache.get(f"revoked_token:{token}") is True


def revoke_token(token: str, duration: int = 86400 * 30):
    """Mark a token as revoked by writing to cache with duration."""
    cache.set(f"revoked_token:{token}", True, timeout=duration)


def validate_access_token(token: str):
    """Validate access token and return the associated active User, or None."""
    if is_token_revoked(token):
        return None
    try:
        data = signing.loads(token, salt=SALT_ACCESS, max_age=900)
        if data.get("token_type") != "access":
            return None
        user_id = data.get("user_id")
        if user_id:
            return User.objects.filter(id=user_id, is_active=True).first()
    except (signing.SignatureExpired, signing.BadSignature):
        return None
    return None


def validate_refresh_token(token: str):
    """Validate refresh token and return the associated active User, or None."""
    if is_token_revoked(token):
        return None
    try:
        data = signing.loads(token, salt=SALT_REFRESH, max_age=86400 * 30)
        if data.get("token_type") != "refresh":
            return None
        user_id = data.get("user_id")
        if user_id:
            return User.objects.filter(id=user_id, is_active=True).first()
    except (signing.SignatureExpired, signing.BadSignature):
        return None
    return None


def mobile_auth_required(view_func):
    """Decorator to enforce short-lived access token authentication.
    Injects request.user, request.driver, and request.auth_token.
    """
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        elif auth_header.startswith("Token "):
            token = auth_header[6:]

        if not token:
            return JsonResponse({
                "error": {
                    "code": "unauthorized",
                    "message": "Authentication token required."
                }
            }, status=401)

        user = validate_access_token(token)
        if not user:
            return JsonResponse({
                "error": {
                    "code": "unauthorized",
                    "message": "Invalid or expired token."
                }
            }, status=401)

        request.user = user
        request.auth_token = token
        
        # Inject driver profile
        driver = user.driver_profiles.first()
        if not driver:
            return JsonResponse({
                "error": {
                    "code": "forbidden",
                    "message": "Authenticated user is not linked to any Driver profile."
                }
            }, status=403)
            
        request.driver = driver
        return view_func(request, *args, **kwargs)

    return wrapped_view
