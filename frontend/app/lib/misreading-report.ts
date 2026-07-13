export interface MisreadingReportPayload {
  episode_id: number
  article_id?: number | null
  audio_generation_id?: string | null
  playback_position?: number | null
  target_sentence: string
  incorrect_reading: string
  correct_reading: string
  notes: string
}

export async function submitMisreadingReport(
  data: MisreadingReportPayload,
): Promise<void> {
  const res = await fetch('/api/misreading-reports', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    const detail = (() => {
      try {
        const parsed = JSON.parse(body)
        if (typeof parsed.detail === 'string') return parsed.detail
        if (Array.isArray(parsed.detail)) {
          return parsed.detail.map((e: { msg: string }) => e.msg).join('、')
        }
      } catch {}
      return body
    })()
    throw new Error(detail || `送信に失敗しました (${res.status})`)
  }
}
