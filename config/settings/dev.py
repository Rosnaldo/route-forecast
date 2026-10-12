from .base import *  # noqa: F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
# Run Celery tasks in-process when no worker/Redis is running: CELERY_TASK_ALWAYS_EAGER=true
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
