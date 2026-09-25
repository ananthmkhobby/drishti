import type { NextConfig } from "next";
import path from "path";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // ── Dev-only: allow LAN + ngrok origins to access HMR websocket ─────────────
  allowedDevOrigins: [
    // LAN IPs — wildcard covers any 192.168.x.x so we never chase the IP again
    "192.168.*.*",
    // ngrok tunnels — the wildcard covers any xxxx.ngrok-free.app domain
    "*.ngrok-free.app",
    "*.ngrok.io",
  ],

  // ── API proxy — rewrites /api/backend/* → backend FastAPI ────────────────────
  // This lets the phone (via ngrok HTTPS frontend) reach the backend without
  // mixed-content issues, even though the backend is plain HTTP on localhost.
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${BACKEND_URL}/v1/:path*`,
      },
    ];
  },

  // Pin Turbopack root (resolved relative to this file, so it works on any machine)
  turbopack: {
    root: path.resolve(__dirname),
  },

  // Same problem, different subsystem: `turbopack.root` only fixes `next dev`'s
  // workspace-root inference. `next build`'s output file tracing has its own,
  // separate root-inference step that needs this to avoid the same error.
  outputFileTracingRoot: path.resolve(__dirname),
};

export default nextConfig;
