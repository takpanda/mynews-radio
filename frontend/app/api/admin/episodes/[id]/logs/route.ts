import { NextRequest } from 'next/server'
import { API_BASE, requireAdminSession } from '../../../auth'

export async function GET(request: NextRequest, props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized

  const { searchParams } = new URL(request.url)
  const cookie = request.headers.get('cookie') ?? ''
  let upstreamUrl = `${API_BASE}/admin/episodes/${params.id}/logs`
  if (searchParams.toString()) {
    upstreamUrl += `?${searchParams.toString()}`
  }

  try {
    const upstream = await fetch(upstreamUrl, {
      headers: { 'Content-Type': 'application/json', Cookie: cookie },
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
