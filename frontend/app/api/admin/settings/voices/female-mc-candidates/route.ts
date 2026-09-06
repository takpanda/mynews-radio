import { NextRequest } from 'next/server'
import { API_BASE, requireAdminSession } from '../../../auth'

async function proxy(request: NextRequest, method: 'GET' | 'POST') {
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized

  const cookie = request.headers.get('cookie') ?? ''
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Cookie: cookie }
  const body = method === 'POST' ? await request.text() : undefined

  try {
    const upstream = await fetch(`${API_BASE}/settings/voices/female-mc-candidates`, {
      method,
      headers,
      ...(body !== undefined ? { body } : {}),
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

export async function GET(request: NextRequest) {
  return proxy(request, 'GET')
}

export async function POST(request: NextRequest) {
  return proxy(request, 'POST')
}
