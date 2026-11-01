import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on 5173. `/api` and `/health` are proxied to the backend so the
// browser always talks to a single origin (no CORS, no base-URL plumbing).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "VITE_");
  const target = env.VITE_API_BASE_URL || "http://localhost:8100";
  const proxy = {
    "/api": { target, changeOrigin: true },
    "/health": { target, changeOrigin: true },
    // Dev-only: sample trace replay served by scripts/mock-server.mjs (404 on the real backend).
    "/__mock": { target, changeOrigin: true },
  };

  return {
    // Only ever read env files from frontend/ (never from the repo root, which holds backend secrets).
    envDir: import.meta.dirname,
    plugins: [react()],
    server: { port: 5173, strictPort: true, proxy },
    preview: { port: 4173, proxy },
    build: {
      target: "es2022",
      chunkSizeWarningLimit: 700, // the livekit chunk is ~590 kB by itself
      rolldownOptions: {
        output: {
          // Keep livekit-client out of the app chunk so UI changes don't bust its cache.
          codeSplitting: {
            groups: [{ name: "livekit", test: /node_modules[\\/](livekit-client|@livekit|jose|@bufbuild)[\\/]/ }],
          },
        },
      },
    },
  };
});
