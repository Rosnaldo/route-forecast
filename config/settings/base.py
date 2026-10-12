"""
Base settings shared by every environment.

Environment-specific modules (dev/test/prod) import * from here and override.
All secrets and environment-dependent values come from environment variables
(12-factor app), parsed by django-environ. A local `.env` file is read in dev.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

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
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # SearchVector, GinIndex, ArrayField...
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "storages",
]
LOCAL_APPS = [
    "apps.core",
    "apps.users",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Order matters: each middleware wraps the ones below it (onion model).
MIDDLEWARE = [
    "apps.core.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestTimingMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ----------------------------------------------------------------------- database
# DATABASE_URL example: postgres://shop:shop@localhost:5432/shop
DATABASES = {"default": env.db("DATABASE_URL", default="postgres://shop:shop@localhost:5432/shop")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------- auth
AUTH_USER_MODEL = "users.User"  # minimal custom user, used by the admin
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ----------------------------------------------------------------------------- i18n
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------- static & media
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # `collectstatic` target, served by nginx/whitenoise
STATICFILES_DIRS = [BASE_DIR / "static"]
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

# -------------------------------------------------------------------------- email
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Shop <no-reply@shop.local>")

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
    "loggers": {
        "django.db.backends": {"level": env("DB_LOG_LEVEL", default="WARNING")},
    },
}
