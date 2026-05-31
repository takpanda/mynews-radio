import { NextRequest } from 'next/server'

const API_BASE = process.env.API_BASE ?? 'http://api:8010'

export async function POST(request: NextRequest) {
  const body = await request.json()

  const upstream = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
  })

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'X-Accel-Buffering': 'no',
    },
  })
}
