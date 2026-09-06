import { NextRequest } from 'next/server'
import { API_BASE, requireAdminSession } from '../../../../../auth'

export async function GET(request: NextRequest, props: { params: Promise<{ voice_name: string }> }) {
  const params = await props.params
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized

  const cookie = request.headers.get('cookie') ?? ''
  const upstreamUrl = `${API_BASE}/settings/voices/categories/samples/${encodeURIComponent(params.voice_name)}`

  try {
    const upstream = await fetch(upstreamUrl, {
      headers: { Cookie: cookie },
      cache: 'no-store',
    })
    if (!upstream.ok) {
      const body = await upstream.text().catch(() => '')
      return new Response(body, {
        status: upstream.status,
        headers: { 'Content-Type': upstream.headers.get('content-type') ?? 'application/json' },
      })
    }
    const body = await upstream.arrayBuffer()
    const headers: Record<string, string> = {
      'Content-Type': upstream.headers.get('content-type') ?? 'audio/wav',
    }
    const cacheControl = upstream.headers.get('cache-control')
    if (cacheControl) headers['Cache-Control'] = cacheControl
    return new Response(body, { status: upstream.status, headers })
  } catch (err) {
    console.error('upstream fetch error:', err)
    return new Response(JSON.stringify({ error: 'upstream error' }), {
      status: 504,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
