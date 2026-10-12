import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("shop")
# Read every CELERY_* setting from Django settings (CELERY_BROKER_URL -> broker_url, ...).
app.config_from_object("django.conf:settings", namespace="CELERY")
# Find `tasks.py` in every installed app.
app.autodiscover_tasks()
