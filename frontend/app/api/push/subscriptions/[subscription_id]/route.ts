import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ subscription_id: string }> },
) {
  const { subscription_id } = await params

  try {
    const upstream = await fetch(
      `${API_BASE}/push/subscriptions/${encodeURIComponent(subscription_id)}`,
      { method: "DELETE" },
    )
    const data = upstream.status === 204 ? null : await upstream.text()
    return new Response(data, {
      status: upstream.status === 204 ? 204 : upstream.status,
      headers: data ? { "Content-Type": "application/json" } : undefined,
    })
  } catch (err) {
    console.error("push/subscriptions delete upstream error:", err)
    return new Response(JSON.stringify({ error: "upstream error" }), {
      status: 504,
      headers: { "Content-Type": "application/json" },
    })
  }
}
