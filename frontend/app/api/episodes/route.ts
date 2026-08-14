import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const limit = searchParams.get("limit")
  const offset = searchParams.get("offset")
  const category = searchParams.get("category")

  const params = new URLSearchParams()
  if (limit !== null) params.set("limit", limit)
  if (offset !== null) params.set("offset", offset)
  // この経路は公開アーカイブ専用。管理画面用の include_failed は
  // クライアント入力から上流へ中継しない。
  if (category !== null) params.set("category", category)

  let url = `${API_BASE}/episodes`
  const qs = params.toString()
  if (qs) url += `?${qs}`

  try {
    const upstream = await fetch(url, { cache: "no-store" })
    const data = await upstream.text()
    // 防御的に公開済み条件を再確認する。バックエンド側の公開条件が将来
    // 変わっても、この公開BFFから生成中・失敗回を返さない。
    if (upstream.ok) {
      try {
        const parsed = JSON.parse(data) as
          | Array<{ status?: string; audio_url?: string | null }>
          | { items?: Array<{ status?: string; audio_url?: string | null }>; total?: number; has_next?: boolean }
        const isPublic = (episode: { status?: string; audio_url?: string | null }) =>
          episode.status === "completed" && Boolean(episode.audio_url)
        const publicData = Array.isArray(parsed)
          ? parsed.filter(isPublic)
          : {
              ...parsed,
              items: (parsed.items ?? []).filter(isPublic),
            }
        return new Response(JSON.stringify(publicData), {
          status: upstream.status,
          headers: { "Content-Type": "application/json" },
        })
      } catch {
        return new Response(JSON.stringify({ error: "upstream returned invalid data" }), {
          status: 502,
          headers: { "Content-Type": "application/json" },
        })
      }
    }
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
