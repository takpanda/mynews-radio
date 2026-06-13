import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params

  try {
    const upstream = await fetch(`${API_BASE}/episodes/${id}`, {
      cache: "no-store",
    })

    const data = await upstream.text()

    return new Response(data, {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json",
      },
    })
  } catch (err) {
    console.error("upstream fetch error:", err)
    return new Response(JSON.stringify({ error: "upstream error" }), {
      status: 504,
      headers: { "Content-Type": "application/json" },
    })
  }
}
