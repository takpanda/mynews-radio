import { NextRequest } from 'next/server'

/** 公開プロキシから内部APIへ渡してよい認証情報は管理セッションだけ。 */
export function getAdminSessionCookie(request: NextRequest): string | null {
  const header = request.headers.get('cookie')
  const match = header?.match(/(?:^|;\s*)admin_session=([^;]*)/)
  if (!match || !match[1]) return null
  return `admin_session=${match[1]}`
}
