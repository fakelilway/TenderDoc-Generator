const backendApiBase = process.env.BACKEND_API_BASE_URL || "http://localhost:8000";

/** @type {import("next").NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendApiBase}/api/:path*`
      },
      {
        source: "/health",
        destination: `${backendApiBase}/health`
      }
    ];
  }
};

export default nextConfig;
