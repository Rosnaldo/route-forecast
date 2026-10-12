# syntax=docker/dockerfile:1.7
# Build context: the repository root.
# ---------- build stage: resolve and install dependencies with uv ----------
FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir "uv>=0.12,<0.13"
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Copy only the lockfile first: this layer is cached until dependencies change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# Dev dependencies too (pytest, ruff), so tests can run inside the container.
FROM builder AS builder-dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

# ---------- dev stage: runserver with auto-reload ----------
# No source is copied: docker compose bind-mounts the repository over /app.
FROM python:3.12-slim AS dev
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.dev
# Same UID/GID as the host user, so files created in the bind mount stay yours.
ARG UID=1000
ARG GID=1000
RUN groupadd --gid $GID app && useradd --uid $UID --gid app --home /app app
COPY --from=builder-dev /opt/venv /opt/venv
WORKDIR /app
USER app
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ---------- runtime stage: small image, no build tools, non-root ----------
# Last stage, so a plain `docker build` produces the production image.
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
# ASGI server: gunicorn manages Uvicorn workers.
CMD ["gunicorn", "config.asgi:application", "-c", "docker/gunicorn.conf.py"]
