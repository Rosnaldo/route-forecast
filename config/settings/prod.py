"""
Production settings, for the Docker Compose deployment.

- Configuration and secrets: environment variables (the .env file, as in development).
- Cache/broker: the Redis service via REDIS_URL (no database).
- Static files: served by the app itself (WhiteNoise, see base.py).
"""

from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = env("SECRET_KEY")  # no default: fail fast if missing

# Behind a reverse proxy (nginx) that terminates TLS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405  (one JSON object per line)
