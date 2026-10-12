# syntax=docker/dockerfile:1.7
# ---------- build stage: resolve and install dependencies with uv ----------
FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir "uv>=0.12,<0.13"
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Copy only the lockfile first: this layer is cached until dependencies change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# ---------- runtime stage: small image, no build tools, non-root ----------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app:app . .
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput --settings=config.settings.dev
USER app
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
# ASGI server: gunicorn manages Uvicorn workers.
CMD ["gunicorn", "config.asgi:application", "-c", "docker/gunicorn.conf.py"]
