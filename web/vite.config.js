import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into the package the API serves, so one process serves the page and the
// endpoints and the demo has no second thing to start.
export default defineConfig({
  plugins: [react()],
  // Served from a sub-path locally, where FastAPI mounts the build under /app/,
  // and from the root on Vercel, where the CDN serves the directory itself.
  base: process.env.VERCEL ? "/" : "/app/",
  build: { outDir: "../src/intentguard/api/static/app", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
