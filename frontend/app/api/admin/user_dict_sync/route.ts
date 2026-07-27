import { NextRequest } from "next/server"
import { API_BASE, requireAdminSession } from "../auth"

export async function POST(request: NextRequest) {
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized

  const body = await request.text()
  const upstreamUrl = `${API_BASE}/admin/user_dict_sync`

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  const cookie = request.headers.get("cookie")
  if (cookie) {
    headers["Cookie"] = cookie
  }

  try {
    const upstream = await fetch(upstreamUrl, {
      method: "POST",
      headers,
      body,
    })
    const data = await upstream.text()
    return new Response(data, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    })
  } catch (err) {
    console.error("upstream fetch error:", err)
    return new Response(
      JSON.stringify({ detail: "AIVIS Speech service unavailable" }),
      { status: 504, headers: { "Content-Type": "application/json" } },
    )
  }
}
