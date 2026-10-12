"""
Production settings (AWS).

- Database: RDS PostgreSQL via DATABASE_URL (sslmode=require).
- Secrets: AWS Secrets Manager, merged into the environment before settings are read.
- Media/static: S3 behind CloudFront (django-storages).
- Credentials: none in code/env — the ECS task role / EKS IRSA role grants IAM access.
"""

from apps.core.aws import load_secrets_into_environ

load_secrets_into_environ()  # must run before `from .base import *` reads env vars

from .base import *  # noqa: E402,F403
from .base import env  # noqa: E402

DEBUG = False
SECRET_KEY = env("SECRET_KEY")  # no default: fail fast if missing

DATABASES["default"]["OPTIONS"] = {"sslmode": env("DB_SSLMODE", default="require")}  # noqa: F405

# Behind nginx / ALB, which terminates TLS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True

AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
if AWS_STORAGE_BUCKET_NAME:
    AWS_S3_REGION_NAME = env("AWS_REGION", default="us-east-1")
    AWS_S3_CUSTOM_DOMAIN = env("AWS_CLOUDFRONT_DOMAIN", default=None)  # e.g. dxxxx.cloudfront.net
    AWS_DEFAULT_ACL = None  # bucket is private; CloudFront reads it through OAC
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = AWS_S3_CUSTOM_DOMAIN is None  # presigned URLs if no CDN
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": {"location": "media"}},
        "staticfiles": {
            "BACKEND": "storages.backends.s3.S3ManifestStaticStorage",
            "OPTIONS": {"location": "static"},
        },
    }

LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405  (CloudWatch-friendly)
