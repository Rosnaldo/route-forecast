#!/bin/bash

# Rebuilds the dev backend image (shop-backend:dev, docker-compose.yml's `backend`).
# Source code is bind-mounted at runtime, so this only needs to run after Python
# dependencies change (pyproject.toml / uv.lock), not on every code change.
# Pass --up to also recreate the running backend container with the new image.
set -euo pipefail

cd "$(dirname "$0")"

echo "Building the backend image (docker/backend/Dockerfile, target dev)..."
docker compose build backend
echo "Image shop-backend:dev built successfully!"

if [[ "${1:-}" == "--up" ]]; then
  docker compose up -d --no-deps backend
fi
