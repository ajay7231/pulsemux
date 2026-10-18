import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "/dashboard/",
  build: { outDir: "../worker-py/web/dashboard", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8001",
      "/ws": { target: "ws://127.0.0.1:8001", ws: true },
      "/simulator": "http://127.0.0.1:8001",
      "/static": "http://127.0.0.1:8001",
    },
  },
});
