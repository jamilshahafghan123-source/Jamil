import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy the API and WebSocket to the local backend so the browser
// talks to one origin and no CORS or token-in-URL juggling is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8080", ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
