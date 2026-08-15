from .base import *  # noqa: F403

DEBUG = env("DEBUG", default=True)  # noqa: F405

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
