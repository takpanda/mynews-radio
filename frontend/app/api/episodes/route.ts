import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const limit = searchParams.get("limit")
  const offset = searchParams.get("offset")
  const include_failed = searchParams.get("include_failed")

  const params = new URLSearchParams()
  if (limit !== null) params.set("limit", limit)
  if (offset !== null) params.set("offset", offset)
  if (include_failed !== null) params.set("include_failed", include_failed)

  let url = `${API_BASE}/episodes`
  const qs = params.toString()
  if (qs) url += `?${qs}`

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
