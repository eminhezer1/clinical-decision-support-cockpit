import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = dirname(fileURLToPath(import.meta.url));
const backendInternalUrl = (
  process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    proxyTimeout: 630_000,
  },
  turbopack: {
    root: rootDir,
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/clinical/:path*",
        destination: `${backendInternalUrl}/api/v1/clinical/:path*`,
      },
    ];
  },
};

export default nextConfig;
