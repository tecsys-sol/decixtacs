import type { NextConfig } from "next";

/**
 * In development `/api/*` is proxied to the FastAPI backend (API_PROXY_TARGET, default
 * http://localhost:8000) so the browser can use same-origin requests. In production the
 * ingress routes /api to the backend; set API_PROXY_TARGET at build time only if the
 * Next.js server itself should proxy.
 */
const isDev = process.env.NODE_ENV !== "production";
const proxyTarget = process.env.API_PROXY_TARGET || (isDev ? "http://localhost:8000" : "");

const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    if (!proxyTarget) return [];
    return [{ source: "/api/:path*", destination: `${proxyTarget.replace(/\/$/, "")}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
