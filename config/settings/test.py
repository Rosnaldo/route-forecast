"""Fast, hermetic settings for pytest: no database, in-memory cache."""

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-secret-key-at-least-32-bytes-long-for-hs256"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405  (no collectstatic in tests)
