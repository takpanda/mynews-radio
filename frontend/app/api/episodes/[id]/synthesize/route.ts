import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"
const FETCH_TIMEOUT_MS = Number(process.env.FETCH_TIMEOUT_MS) || 360_000
const API_KEY = process.env.API_KEY

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
    }
    if (API_KEY) {
      headers["Authorization"] = `Bearer ${API_KEY}`
    }

    const upstream = await fetch(`${API_BASE}/episodes/${params.id}/synthesize`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    if (!upstream.ok) {
      const errorBody = await upstream.text()
      return new Response(errorBody, {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
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
