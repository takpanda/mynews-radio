import { NextRequest, NextResponse } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params

  try {
    const upstream = await fetch(`${API_BASE}/mcs/${encodeURIComponent(id)}/photo`, {
      cache: "no-store",
    })
    if (!upstream.ok) {
      return new Response(null, {
        status: upstream.status,
        headers: { "Cache-Control": "no-store" },
      })
    }

    // 公開画像でセッションに依存しない。URLの ?v= が差し替え時のキャッシュバスターになる
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "image/webp",
        "Cache-Control": "public, max-age=86400",
      },
    })
  } catch {
    return NextResponse.json(
      { error: "upstream error" },
      { status: 504, headers: { "Cache-Control": "no-store" } },
    )
  }
}
