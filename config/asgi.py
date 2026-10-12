"""ASGI entrypoint, served by uvicorn or gunicorn + UvicornWorker.
Runs sync and async Django views alike."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
application = get_asgi_application()
