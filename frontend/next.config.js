/** @type {import('next').NextConfig} */
const nextConfig = {
  // Docker内のdevサーバーとホスト側プレビューが同じ .next を奪い合わないよう、
  // 環境変数でビルドディレクトリを切り替えられるようにする
  distDir: process.env.NEXT_DIST_DIR || '.next',
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
