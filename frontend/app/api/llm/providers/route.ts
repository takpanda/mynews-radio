import { NextRequest } from 'next/server'
import { getAdminSessionCookie } from '../../session-cookie'

const API_BASE = process.env.API_BASE ?? 'http://localhost:8010'

export async function GET(request: NextRequest) {
  const headers: Record<string, string> = {}
  const cookie = getAdminSessionCookie(request)
  if (cookie) headers.Cookie = cookie

  try {
    const upstream = await fetch(`${API_BASE}/llm/providers`, { headers, cache: 'no-store' })
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (error) {
    console.error('upstream fetch error:', error)
    return new Response(JSON.stringify({ error: 'upstream error' }), {
      status: 504,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
