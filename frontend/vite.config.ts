import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The browser only ever talks to this dev server; /api is proxied to the local backend.
// No API keys live in the frontend.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const backend = env.CVFORGE_BACKEND_URL || "http://127.0.0.1:8000";
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: env.CVFORGE_FRONTEND_HOST || "127.0.0.1",
      port: Number(env.CVFORGE_FRONTEND_PORT || 5173),
      proxy: { "/api": { target: backend, changeOrigin: false } },
    },
  };
});
