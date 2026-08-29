import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { trustedRouteStaticBudget } from "./scripts/trusted-route-budget.mjs";

export default defineConfig({
  plugins: [react(), trustedRouteStaticBudget(250 * 1024)],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          icons: ["lucide-react"],
        },
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
