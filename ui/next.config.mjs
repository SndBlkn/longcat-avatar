/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // Allow large request bodies for base64 uploads (image + audio)
    serverActions: { bodySizeLimit: "50mb" },
  },
};

export default nextConfig;
