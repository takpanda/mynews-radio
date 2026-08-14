import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params

  try {
    const upstream = await fetch(`${API_BASE}/episodes/${id}`, {
      cache: "no-store",
    })

    const data = await upstream.text()

    // 公開詳細は、完成済みで実際に再生可能な回だけに限定する。
    // 生成中の進捗・失敗理由を公開経路から漏らさない。
    if (upstream.ok) {
      try {
        const episode = JSON.parse(data) as { status?: string; audio_url?: string | null }
        if (episode.status !== "completed" || !episode.audio_url) {
          return new Response(JSON.stringify({ detail: "Episode not found" }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
          })
        }
      } catch {
        return new Response(JSON.stringify({ error: "upstream returned invalid data" }), {
          status: 502,
          headers: { "Content-Type": "application/json" },
        })
      }
    }

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
