import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The browser talks only to /api/*. Vite forwards that to the existing
// FastAPI service on 127.0.0.1:3000, so no CORS headers need to be added
// to the backend at all.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
