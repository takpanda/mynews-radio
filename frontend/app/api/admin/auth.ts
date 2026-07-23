import { NextRequest } from 'next/server'

const API_BASE = process.env.API_BASE ?? 'http://api:8010'

export async function requireAdminSession(request: NextRequest): Promise<Response | null> {
  const cookie = request.headers.get('cookie')
  if (!cookie || !/(^|;\s*)admin_session=/.test(cookie)) {
    return new Response(JSON.stringify({ detail: 'Not authenticated' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    const response = await fetch(`${API_BASE}/admin/me`, {
      headers: { Cookie: cookie },
      cache: 'no-store',
    })
    if (!response.ok) {
      return new Response(JSON.stringify({ detail: 'Not authenticated' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return null
  } catch {
    return new Response(JSON.stringify({ detail: 'Authentication service unavailable' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}

export { API_BASE }
