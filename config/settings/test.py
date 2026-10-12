"""Fast, hermetic settings for pytest. Postgres is still required, so tests run on
the same engine as production."""

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-secret-key-at-least-32-bytes-long-for-hs256"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Run Celery tasks synchronously, in-process, and surface their exceptions.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405  (no collectstatic in tests)
