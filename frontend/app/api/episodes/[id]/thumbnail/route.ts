import { NextResponse } from "next/server"
import { getAdminSessionCookie } from "../../../session-cookie"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params

  try {
    const headers: Record<string, string> = {}
    const cookie = getAdminSessionCookie(_request)
    if (cookie) headers.Cookie = cookie

    const upstream = await fetch(`${API_BASE}/episodes/${encodeURIComponent(id)}/thumbnail`, {
      cache: "no-store",
      headers,
    })
    if (!upstream.ok) {
      return new Response(null, { status: upstream.status })
    }

    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "image/png",
        "Cache-Control": "public, max-age=3600",
      },
    })
  } catch {
    return NextResponse.json({ error: "upstream error" }, { status: 504 })
  }
}
