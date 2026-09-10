/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export — served by Render's free Static Site (no server, no sleep).
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
