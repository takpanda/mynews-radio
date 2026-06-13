/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const apiBase = process.env.API_BASE ?? 'http://api:8010'
    return [
      {
        source: '/audio',
        destination: `${apiBase}/audio`,
      },
      {
        source: '/audio/:path*',
        destination: `${apiBase}/audio/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
