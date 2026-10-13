import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The repo-root .env is shared with Django. In Docker it isn't mounted here, but
// docker compose passes it in as process.env, which loadEnv also reads.
const envDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, "");
  const backend = env.BACKEND_URL || "http://localhost:8000";
  // The dev nginx (nginx/.env.dev) forwards requests for its domain here.
  const domain = env.BASE_DOMAIN;

  return {
    plugins: [react()],
    envDir,
    // Expose only the browser key, not the whole .env (SECRET_KEY etc.).
    define: {
      __GOOGLE_MAPS_API_KEY__: JSON.stringify(env.GOOGLE_MAPS_API_KEY || ""),
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
      strictPort: true,
      allowedHosts: domain ? [domain, `www.${domain}`] : [],
      // Same origin in development: no CORS needed.
      proxy: {
        "/api": backend,
        "/health": backend,
      },
    },
  };
});
