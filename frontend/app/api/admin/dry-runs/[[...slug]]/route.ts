import { NextRequest } from 'next/server'
import { API_BASE, requireAdminSession } from '../../auth'

function buildUpstreamUrl(request: NextRequest): string {
  const { pathname, searchParams } = new URL(request.url)
  const suffix = pathname.replace(/^\/api\/admin\/dry-runs/, '') || ''
  let url = `${API_BASE}/admin/dry-runs${suffix}`
  if (searchParams.toString()) {
    url += `?${searchParams.toString()}`
  }
  return url
}

export async function GET(request: NextRequest) {
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized

  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const cookie = request.headers.get('cookie')
  if (cookie) headers['Cookie'] = cookie

  try {
    const upstream = await fetch(buildUpstreamUrl(request), {
      method: 'GET',
      headers,
      cache: 'no-store',
    })
    const data = await upstream.text()
    return new Response(data, {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (err) {
    console.error('upstream fetch error:', err)
    return new Response(JSON.stringify({ error: 'upstream error' }), {
      status: 504,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
