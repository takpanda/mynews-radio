import { NextRequest } from "next/server"
import { getAdminSessionCookie } from "../session-cookie"

const API_BASE = process.env.API_BASE ?? "http://localhost:8010"

export async function POST(request: NextRequest) {
  const body = await request.json()

  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "Idempotency-Key": request.headers.get("Idempotency-Key") ?? crypto.randomUUID(),
    }
    const cookie = getAdminSessionCookie(request)
    if (cookie) headers["Cookie"] = cookie

    const upstream = await fetch(`${API_BASE}/generate`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    })

    const data = await upstream.text()

    const responseHeaders = new Headers({ "Content-Type": "application/json" })
    const retryAfter = upstream.headers?.get("Retry-After")
    if (retryAfter) responseHeaders.set("Retry-After", retryAfter)

    return new Response(data, { status: upstream.status, headers: responseHeaders })
  } catch (err) {
    console.error("upstream fetch error:", err)
    return new Response(JSON.stringify({ error: "upstream error" }), {
      status: 504,
      headers: { "Content-Type": "application/json" },
    })
  }
}
