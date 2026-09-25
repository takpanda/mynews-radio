import { NextRequest } from "next/server"

const API_BASE = process.env.API_BASE ?? "http://api:8010"

export async function POST(request: NextRequest) {
  let body: unknown
  try {
    body = await request.json()
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    })
  }

  try {
    const adminSession = request.cookies.get("admin_session")?.value
    const upstream = await fetch(`${API_BASE}/push/subscriptions/associate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(adminSession ? { Cookie: `admin_session=${adminSession}` } : {}),
      },
      body: JSON.stringify(body),
    })
    return new Response(null, { status: upstream.status })
  } catch (err) {
    console.error("push/subscriptions association upstream error:", err)
    return new Response(JSON.stringify({ error: "upstream error" }), {
      status: 504,
      headers: { "Content-Type": "application/json" },
    })
  }
}
