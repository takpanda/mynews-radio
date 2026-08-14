import { NextRequest } from "next/server"
import { getAdminSessionCookie } from "../../session-cookie"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params

  try {
    const headers: Record<string, string> = {}
    const cookie = getAdminSessionCookie(request)
    if (cookie) headers["Cookie"] = cookie

    // 公開/管理の取得条件はバックエンドの GET /episodes/{id} が判定する。
    // ここでは admin_session だけを転送し、それ以外のCookieは渡さない。
    const upstream = await fetch(`${API_BASE}/episodes/${id}`, {
      cache: "no-store",
      headers,
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
