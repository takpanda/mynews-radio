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

  const size = request.nextUrl.searchParams.get("size")
  if (size !== null && !SIZES.has(size)) {
    // 上流APIと同様に、未知のsizeは原寸PNGへ黙って切り替えず422で拒否する
    return new Response(null, { status: 422, headers: { "Cache-Control": PRIVATE_NO_STORE } })
  }

  try {
    const headers: Record<string, string> = {}
    const cookie = getAdminSessionCookie(request)
    if (cookie) headers.Cookie = cookie

    const query = size ? `?size=${size}` : ""
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
