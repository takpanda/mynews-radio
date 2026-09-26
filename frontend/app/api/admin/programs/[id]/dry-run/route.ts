import { NextRequest } from 'next/server'
import { API_BASE, requireAdminSession } from '../../../auth'

export async function POST(request: NextRequest, props: { params: Promise<{ id: string }> }) {
  const params = await props.params
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized

  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const cookie = request.headers.get('cookie')
  if (cookie) headers['Cookie'] = cookie
  const idempotencyKey = request.headers.get('idempotency-key')
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey

  const body = await request.text()

  try {
    const upstream = await fetch(`${API_BASE}/admin/programs/${encodeURIComponent(params.id)}/dry-run`, {
      method: 'POST',
      headers,
      body,
    })
    const data = await upstream.text()
    const responseHeaders = new Headers({ 'Content-Type': 'application/json' })
    const retryAfter = upstream.headers.get('Retry-After')
    if (retryAfter) responseHeaders.set('Retry-After', retryAfter)
    return new Response(data, { status: upstream.status, headers: responseHeaders })
  } catch (err) {
    console.error('upstream fetch error:', err)
    return new Response(JSON.stringify({ error: 'upstream error' }), {
      status: 504,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
