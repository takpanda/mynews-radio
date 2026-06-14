import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://localhost:8010"

export async function POST(request: NextRequest) {
  const body = await request.json()

  try {
    const upstream = await fetch(`${API_BASE}/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
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
