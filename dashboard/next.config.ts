import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Native module — keep out of the webpack/turbopack bundle for API routes.
  serverExternalPackages: ["better-sqlite3"],
};

export default nextConfig;
