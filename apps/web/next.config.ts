import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@picovoice/porcupine-web", "@picovoice/web-voice-processor"],
};

export default nextConfig;
