import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://localhost:8010"
const API_KEY = process.env.API_KEY

export async function POST(request: NextRequest) {
  const body = await request.json()

  try {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    }
    if (API_KEY) {
      headers["Authorization"] = `Bearer ${API_KEY}`
    }

    const upstream = await fetch(`${API_BASE}/generate`, {
      method: "POST",
      headers,
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
