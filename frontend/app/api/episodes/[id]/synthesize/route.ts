import { NextRequest } from "next/server"
import { getAdminSessionCookie } from "../../../session-cookie"

const API_BASE = process.env.API_BASE ?? "http://api:8010"
const FETCH_TIMEOUT_MS = Number(process.env.FETCH_TIMEOUT_MS) || 360_000

export async function POST(
  request: NextRequest,
  { params }: { params: { id: string } },
) {
  const body = await request.json()
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)

  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "Idempotency-Key": request.headers.get("Idempotency-Key") ?? crypto.randomUUID(),
    }
    const cookie = getAdminSessionCookie(request)
    if (cookie) headers["Cookie"] = cookie

    const upstream = await fetch(`${API_BASE}/episodes/${params.id}/synthesize`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    if (!upstream.ok) {
      const errorBody = await upstream.text()
      const responseHeaders = new Headers({ "Content-Type": "application/json" })
      const retryAfter = upstream.headers.get("Retry-After")
      if (retryAfter) responseHeaders.set("Retry-After", retryAfter)
      return new Response(errorBody, {
        status: upstream.status,
        headers: responseHeaders,
      })
    }

    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
      },
    })
  } catch (err) {
    console.error("upstream fetch error:", err)
    return new Response(JSON.stringify({ error: "upstream timeout or error" }), {
      status: 504,
      headers: { "Content-Type": "application/json" },
    })
  } finally {
    clearTimeout(timer)
  }
}
