#!/bin/bash

# Rebuilds the production backend image (shop-backend:prod, docker-compose.prod.yml's
# `backend`) and restarts the stack with it. The prod image contains the code itself
# (no bind mount), so run this after every pull that changes the backend.
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE=(docker compose -f docker-compose.prod.yml)

echo "Building the backend image (docker/backend/Dockerfile, target runtime)..."
"${COMPOSE[@]}" build backend
echo "Image shop-backend:prod built successfully!"

# Recreates only what changed: the backend, plus nginx when its config changed.
"${COMPOSE[@]}" up -d
