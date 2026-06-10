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
      {
        source: '/episodes',
        destination: `${apiBase}/episodes`,
      },
      {
        source: '/episodes/:path*',
        destination: `${apiBase}/episodes/:path*`,
      },
      {
        source: '/articles',
        destination: `${apiBase}/articles`,
      },
      {
        source: '/articles/:path*',
        destination: `${apiBase}/articles/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
