import { defineConfig, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";

// The API runs separately; the dev server forwards /api to it so the browser sees one origin,
// exactly like nginx does in production.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

const api: ProxyOptions = {
  target: apiTarget,
  changeOrigin: true,
  configure(proxy) {
    proxy.on("proxyReq", (proxyReq, req) => {
      // Server-sent events must arrive as they are written. Asking for an uncompressed
      // response keeps anything in between from buffering the stream to compress it.
      if (req.headers.accept?.includes("text/event-stream") || req.url?.endsWith("/events")) {
        proxyReq.setHeader("Accept-Encoding", "identity");
      }
    });
    proxy.on("proxyRes", (proxyRes) => {
      if (proxyRes.headers["content-type"]?.startsWith("text/event-stream")) {
        proxyRes.headers["cache-control"] = "no-cache, no-transform";
        proxyRes.headers["x-accel-buffering"] = "no";
        delete proxyRes.headers["content-length"];
      }
    });
  },
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": api } },
  preview: { port: 4173, proxy: { "/api": api } },
  build: {
    // The charts chunk is loaded lazily on the campaign page only.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ["recharts"],
          vendor: ["react", "react-dom", "react-router", "@tanstack/react-query"],
        },
      },
    },
  },
});
