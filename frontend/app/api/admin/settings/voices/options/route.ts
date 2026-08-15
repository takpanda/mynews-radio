import { NextRequest } from 'next/server'
import { API_BASE, requireAdminSession } from '../../../auth'

export async function GET(request: NextRequest) {
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized

  const cookie = request.headers.get('cookie') ?? ''

  try {
    const upstream = await fetch(`${API_BASE}/settings/voices/options`, {
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
