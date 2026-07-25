import { NextRequest } from 'next/server'

const API_BASE = process.env.API_BASE ?? 'http://localhost:8010'
const API_KEY = process.env.API_KEY

async function proxy(request: NextRequest, method: 'GET' | 'PUT' | 'DELETE') {
  const headers: Record<string, string> = {}
  if (API_KEY) headers.Authorization = `Bearer ${API_KEY}`
  if (method === 'PUT') headers['Content-Type'] = 'application/json'
  const upstream = await fetch(`${API_BASE}/settings`, {
    method,
    headers,
    ...(method === 'PUT' ? { body: await request.text() } : {}),
  })
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export async function GET(request: NextRequest) { return proxy(request, 'GET') }
export async function PUT(request: NextRequest) { return proxy(request, 'PUT') }
export async function DELETE(request: NextRequest) { return proxy(request, 'DELETE') }
