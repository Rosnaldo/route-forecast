"""Gunicorn as process manager + Uvicorn workers (ASGI).
Gunicorn: forks/monitors/restarts workers, graceful reloads.
Uvicorn: async event loop per worker (ASGI: sync and async views)."""

import multiprocessing
import os

bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn_worker.UvicornWorker"
timeout = int(os.getenv("GUNICORN_TIMEOUT", 60))
graceful_timeout = 30
keepalive = 5
max_requests = 1000  # recycle workers periodically (protects against leaks)
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "*"  # trust X-Forwarded-* from nginx/ALB
