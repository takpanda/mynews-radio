import { NextRequest } from 'next/server'
import { API_BASE, requireAdminSession } from '../../../../../auth'

export async function POST(
  request: NextRequest,
  props: { params: Promise<{ id: string; idx: string }> },
) {
  const params = await props.params;
  const unauthorized = await requireAdminSession(request)
  if (unauthorized) return unauthorized

  const cookie = request.headers.get('cookie') ?? ''
  const upstreamUrl = `${API_BASE}/admin/episodes/${params.id}/lines/${params.idx}/preview-audio`

  try {
    const upstream = await fetch(upstreamUrl, {
      method: 'POST',
      headers: { Cookie: cookie },
      cache: 'no-store',
    })
    // WAVの音声本体、429/502等のJSONエラーのいずれも、ステータスとContent-Typeを保ったまま
    // そのままバイト列で中継する（レート制限・上流障害を握りつぶさない）。
    const body = await upstream.arrayBuffer()
    const headers: Record<string, string> = {
      'Content-Type': upstream.headers.get('content-type') ?? 'application/json',
    }
    const disposition = upstream.headers.get('content-disposition')
    if (disposition) headers['Content-Disposition'] = disposition
    return new Response(body, { status: upstream.status, headers })
  } catch (err) {
    console.error('upstream fetch error:', err)
    return new Response(JSON.stringify({ error: 'upstream error' }), {
      status: 504,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
