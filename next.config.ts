import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // MT5_BRIDGE_URL / MT5_BRIDGE_TOKEN are deliberately absent from `env` and
  // carry no NEXT_PUBLIC_ prefix, so they stay on the server only.
};

export default nextConfig;
