import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"
const API_KEY = process.env.API_KEY

function buildUpstreamUrl(request: NextRequest): string {
  const { pathname, searchParams } = new URL(request.url)
  const suffix = pathname.replace(/^\/api\/admin\/dictionary/, "") || ""
  let url = `${API_BASE}/admin/dictionary${suffix}`
  if (searchParams.toString()) {
    url += `?${searchParams.toString()}`
  }
  return url
}

function buildHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  if (API_KEY) {
    headers["Authorization"] = `Bearer ${API_KEY}`
  }
  return headers
}

async function proxy(request: NextRequest, method: string) {
  const upstreamUrl = buildUpstreamUrl(request)
  const headers = buildHeaders()
  let body: string | undefined
  if (method !== "GET" && method !== "HEAD") {
    body = await request.text()
  }
  try {
    const upstream = await fetch(upstreamUrl, {
      method,
      headers,
      ...(body ? { body } : {}),
    })
    const data = await upstream.text()
    return new Response(data, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    })
  } catch (err) {
    console.error("upstream fetch error:", err)
    return new Response(JSON.stringify({ error: "upstream error" }), {
      status: 504,
      headers: { "Content-Type": "application/json" },
    })
  }
}

export async function GET(request: NextRequest) {
  return proxy(request, "GET")
}

export async function POST(request: NextRequest) {
  return proxy(request, "POST")
}

export async function PUT(request: NextRequest) {
  return proxy(request, "PUT")
}

export async function PATCH(request: NextRequest) {
  return proxy(request, "PATCH")
}

export async function DELETE(request: NextRequest) {
  return proxy(request, "DELETE")
}
