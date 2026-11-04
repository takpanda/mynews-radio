import { NextRequest } from 'next/server'
import { getAdminSessionCookie } from '../../session-cookie'

const API_BASE = process.env.API_BASE ?? 'http://localhost:8010'

/** /settings/topics 系を内部APIへ中継する。管理セッションCookieのみ転送する。 */
export async function proxyTopics(request: NextRequest, method: 'GET' | 'POST' | 'PUT' | 'DELETE', id?: string) {
  const headers: Record<string, string> = {}
  const cookie = getAdminSessionCookie(request)
  if (cookie) headers.Cookie = cookie
  const hasBody = method === 'POST' || method === 'PUT'
  if (hasBody) headers['Content-Type'] = 'application/json'
  const path = id === undefined ? '/settings/topics' : `/settings/topics/${encodeURIComponent(id)}`
  const upstream = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    ...(hasBody ? { body: await request.text() } : {}),
  })
  const text = await upstream.text()
  if (upstream.status === 204 || text === '') return new Response(null, { status: upstream.status })
  return new Response(text, { status: upstream.status, headers: { 'Content-Type': 'application/json' } })
}
