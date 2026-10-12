# syntax=docker/dockerfile:1.7
# ---------- deps: install node_modules from the lockfile ----------
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

# ---------- dev: Vite dev server with hot reload ----------
# docker compose bind-mounts ./frontend over /app; node_modules stays in a volume.
FROM node:24-alpine AS dev
WORKDIR /app
COPY --from=deps --chown=node:node /app/node_modules ./node_modules
USER node
EXPOSE 5173
# `npm install` first: picks up dependencies added since the image was built (~1s when unchanged).
CMD ["sh", "-c", "npm install --no-audit --no-fund && exec npm run dev"]

# ---------- build: static bundle ----------
FROM deps AS build
COPY . .
# Browser key, baked into the bundle at build time (it is public anyway).
ARG GOOGLE_MAPS_API_KEY=""
ENV GOOGLE_MAPS_API_KEY=$GOOGLE_MAPS_API_KEY
RUN npm run build

# ---------- runtime: nginx serving the bundle ----------
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
