import { NextRequest } from "next/server"
import { API_BASE, requireAdminSession } from "../../auth"


function buildUpstreamUrl(request: NextRequest): string {
  const { pathname, searchParams } = new URL(request.url)
  const suffix = pathname.replace(/^\/api\/admin\/mcs/, "") || ""
  let url = `${API_BASE}/admin/mcs${suffix}`
  if (searchParams.toString()) {
    url += `?${searchParams.toString()}`
  }
  return url
}

function isMultipart(request: NextRequest): boolean {
  return (request.headers.get("content-type") ?? "").toLowerCase().startsWith("multipart/form-data")
}

function buildHeaders(request: NextRequest, multipart: boolean): Record<string, string> {
  // multipartはboundaryを含む元のcontent-typeをそのまま転送する
  const headers: Record<string, string> = {
    "Content-Type": multipart ? (request.headers.get("content-type") as string) : "application/json",
  }
  const cookie = request.headers.get("cookie")
  if (cookie) {
    headers["Cookie"] = cookie
  }
  return headers
}

async function proxy(request: NextRequest, method: string) {
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized
  const upstreamUrl = buildUpstreamUrl(request)
  const multipart = isMultipart(request)
  const headers = buildHeaders(request, multipart)
  let body: string | ArrayBuffer | undefined
  if (method !== "GET" && method !== "HEAD" && method !== "DELETE") {
    body = multipart ? await request.arrayBuffer() : await request.text()
  }
  try {
    const upstream = await fetch(upstreamUrl, {
      method,
      headers,
      ...(body !== undefined && (typeof body === "string" ? body : body.byteLength) ? { body } : {}),
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

export async function DELETE(request: NextRequest) {
  return proxy(request, "DELETE")
}
