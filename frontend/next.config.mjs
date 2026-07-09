const backendApiBase = process.env.BACKEND_API_BASE_URL || "http://localhost:8000";

/** @type {import("next").NextConfig} */
const nextConfig = {
  // 精简的生产打包(自带一个最小 Node 服务)。Docker 部署用,镜像更小、启动更快。
  output: "standalone",
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
