from contextvars import ContextVar
from typing import Any

REQUEST_ID = ContextVar("request_id", default="-")
SENSITIVE_LOG_KEYS = {
    "password",
    "token",
    "authorization",
    "api_key",
    "credential",
    "cookie",
    "secret",
}


def set_request_id(request_id: str):
    return REQUEST_ID.set(request_id)


def reset_request_id(token) -> None:
    REQUEST_ID.reset(token)


class RequestIDLogFilter:
    def filter(self, record) -> bool:
        record.request_id = REQUEST_ID.get()
        return True


def sanitize_log_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(secret in str(key).lower() for secret in SENSITIVE_LOG_KEYS)
            else sanitize_log_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [sanitize_log_value(item) for item in value]
    return value
