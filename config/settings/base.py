"""
Base settings shared by every environment.

Environment-specific modules (dev/test/prod) import * from here and override.
All secrets and environment-dependent values come from environment variables
(12-factor app), parsed by django-environ. A local `.env` file is read in dev.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# Django's own pages (templates, CSS) live with the rest of the frontend.
FRONTEND_DJANGO_DIR = BASE_DIR / "frontend" / "django"

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
environ.Env.read_env(BASE_DIR / ".env")  # no-op if the file does not exist

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# --------------------------------------------------------------------------- apps
# No database: no admin, auth, sessions or contenttypes. State lives in Redis.
DJANGO_APPS = [
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "django_filters",
    "drf_spectacular",
]
LOCAL_APPS = [
    "apps.core",
    "apps.trips",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Order matters: each middleware wraps the ones below it (onion model).
MIDDLEWARE = [
    "apps.core.middleware.RequestIDMiddleware",
    # Before anything that reads or writes the body: compresses responses (route
    # responses are ~1 MB of coordinates and shrink several times), event streams
    # event by event.
    "apps.core.middleware.GZipMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestTimingMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DJANGO_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

# ----------------------------------------------------------------------- database
DATABASES: dict = {}  # none: forecasts and other state live in Redis

# ----------------------------------------------------------------------------- i18n
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------- static & media
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # `collectstatic` target, served by nginx/whitenoise
STATICFILES_DIRS = [FRONTEND_DJANGO_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# -------------------------------------------------------------------------- cache
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"{REDIS_URL}/1",
    }
}

# ------------------------------------------------------------------- google maps
# Server key for the Routes API (restrict by IP, not HTTP referrer).
GOOGLE_ROUTES_API_KEY = env("GOOGLE_ROUTES_API_KEY", default="")

# ----------------------------------------------------------------- REST framework
REST_FRAMEWORK = {
    # Public API: no authentication. Add authentication/permission classes here
    # (globally) or on individual views if that changes.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,  # request.user is None (no auth app lookups)
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1", "v2"],
    # Per-client-IP rate limit (every caller is anonymous).
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": env("API_RATE_LIMIT", default="1000/hour")},
    "EXCEPTION_HANDLER": "apps.core.exception_handler.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Shop API",
    "DESCRIPTION": "Django study project",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ------------------------------------------------------------------------- celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=f"{REDIS_URL}/0")
CELERY_TASK_ACKS_LATE = True  # re-deliver if a worker dies mid-task (tasks must be idempotent)
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 5 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 4 * 60
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE: dict = {}  # periodic tasks: {"name": {"task": "...", "schedule": seconds}}

# ------------------------------------------------------------------------ logging
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.logging.RequestIDFilter"}},
    "formatters": {
        "json": {"()": "apps.core.logging.JSONFormatter"},
        "console": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": env("LOG_FORMAT", default="console"),
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
}
