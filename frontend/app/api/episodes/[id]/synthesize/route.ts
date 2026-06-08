import { NextRequest } from "next/server"

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
    const upstream = await fetch(`${API_BASE}/episodes/${params.id}/synthesize`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })

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
