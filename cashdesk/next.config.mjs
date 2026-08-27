/** @type {import('next').NextConfig} */
const nextConfig = {
  basePath: "/cashdesk",
  assetPrefix: "/cashdesk/",
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
