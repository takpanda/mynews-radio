import { NextRequest } from 'next/server'
import { API_BASE } from '../auth'

export async function POST(request: NextRequest) {
  const response = await fetch(`${API_BASE}/admin/logout`, {
    method: 'POST',
    headers: { Cookie: request.headers.get('cookie') ?? '' },
  })
  const result = new Response(await response.text(), {
    status: response.status,
    headers: { 'Content-Type': 'application/json' },
  })
  const cookie = response.headers.get('set-cookie')
  if (cookie) result.headers.set('set-cookie', cookie)
  return result
}
