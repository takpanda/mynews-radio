import { NextRequest, NextResponse } from "next/server"
import { getAdminSessionCookie } from "../../../session-cookie"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params

  try {
    const headers: Record<string, string> = {}
    const cookie = getAdminSessionCookie(request)
    if (cookie) headers.Cookie = cookie

    const upstream = await fetch(`${API_BASE}/episodes/${encodeURIComponent(id)}/thumbnail`, {
      cache: "no-store",
      headers,
    })
    if (!upstream.ok) {
      return new Response(null, {
        status: upstream.status,
        headers: { "Cache-Control": "private, no-store" },
      })
    }

    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "image/png",
        "Cache-Control": "private, no-store",
      },
    })
  } catch {
    return NextResponse.json(
      { error: "upstream error" },
      { status: 504, headers: { "Cache-Control": "private, no-store" } },
    )
  }
}
