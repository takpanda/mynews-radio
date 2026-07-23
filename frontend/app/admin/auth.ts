import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

const API_BASE = process.env.API_BASE ?? 'http://api:8010'

/** SSR管理ページはCookieの存在ではなく、バックエンドでセッションを検証する。 */
export async function requireAdminSessionForPage(): Promise<void> {
  const token = cookies().get('admin_session')?.value
  if (!token) redirect('/admin/login')

  try {
    const response = await fetch(`${API_BASE}/admin/me`, {
      headers: { Cookie: `admin_session=${token}` },
      cache: 'no-store',
    })
    if (!response.ok) redirect('/admin/login')
  } catch {
    redirect('/admin/login')
  }
}
