/** @type {import('next').NextConfig} */
const nextConfig = {
  basePath: "/finance",
  assetPrefix: "/finance/",
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
