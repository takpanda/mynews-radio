import { NextRequest, NextResponse } from "next/server"
import { getAdminSessionCookie } from "../../../session-cookie"

const API_BASE = process.env.API_BASE ?? "http://api:8010"
const SIZES = new Set(["card", "detail"])
const PRIVATE_NO_STORE = "private, no-store"

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params

  try {
    const headers: Record<string, string> = {}
    const cookie = getAdminSessionCookie(request)
    if (cookie) headers.Cookie = cookie

    const size = request.nextUrl.searchParams.get("size")
    const query = size && SIZES.has(size) ? `?size=${size}` : ""
    const upstream = await fetch(`${API_BASE}/episodes/${encodeURIComponent(id)}/thumbnail${query}`, {
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
        // サイズ指定時は上流の Cache-Control（公開回 public / 非公開回 private）を転送する
        "Cache-Control": upstream.headers.get("cache-control") ?? PRIVATE_NO_STORE,
      },
    })
  } catch {
    return NextResponse.json(
      { error: "upstream error" },
      { status: 504, headers: { "Cache-Control": "private, no-store" } },
    )
  }
}
