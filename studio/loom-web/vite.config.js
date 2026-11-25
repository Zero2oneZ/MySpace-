import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` serves on :5173 and proxies the API to the Python dapp
// server on :8520 (run it in another terminal). Build: `npm run build` → dist/,
// which the dapp server can serve at /dapp/loom.
const API = process.env.MSPC_API || "http://127.0.0.1:8520";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/dapp/api": { target: API, changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
