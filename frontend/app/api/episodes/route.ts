import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const limit = searchParams.get("limit")
  const offset = searchParams.get("offset")

  let url = `${API_BASE}/episodes`
  if (limit !== null && offset !== null) {
    url += `?limit=${limit}&offset=${offset}`
  }

  try {
    const upstream = await fetch(url, { cache: "no-store" })
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
