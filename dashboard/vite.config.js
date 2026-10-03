import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the dashboard runs on :5173 and forwards API/WebSocket calls
// to the Python backend on :8000. After `npm run build`, the backend serves
// the built dashboard itself at http://localhost:8000.
const BACKEND = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 1000 },
  server: {
    port: 5173,
    proxy: {
      "/api": BACKEND,
      "/figures": BACKEND,
      "/ws": { target: BACKEND.replace("http", "ws"), ws: true },
    },
  },
});
