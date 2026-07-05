'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { synthesizeEpisodeStream } from '../lib/api'

interface Props {
  episodeId: number
  compact?: boolean
}

type State = 'idle' | 'loading' | 'success' | 'error'

interface ProgressPayload {
  phase?: string
  message?: string
  status?: string
  episode_id?: number
}

function parseSseChunk(chunk: string): { event: string; payload: ProgressPayload | null } {
  const lines = chunk.split('\n')
  const eventLine = lines.find((line) => line.startsWith('event:'))
  const dataLines = lines.filter((line) => line.startsWith('data:'))
  const event = eventLine ? eventLine.slice('event:'.length).trim() : 'message'
  const data = dataLines.map((line) => line.slice('data:'.length)).join('\n')
  try {
    return { event, payload: JSON.parse(data) as ProgressPayload }
  } catch {
    return { event, payload: null }
  }
}

export default function SynthesizeAudioButton({ episodeId, compact = false }: Props) {
  const [state, setState] = useState<State>('idle')
  const [statusMessage, setStatusMessage] = useState('')
  const router = useRouter()

  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    setState('loading')
    setStatusMessage('音声を合成しています...')

    try {
      const response = await synthesizeEpisodeStream(episodeId)

      if (!response.ok) {
        const errorBody = await response.text().catch(() => '')
        try {
          const parsed = JSON.parse(errorBody)
          if (response.status === 401) {
            setStatusMessage('API キーが設定されていません。サーバー設定が必要です。')
          } else if (response.status === 429) {
            setStatusMessage('レート制限に達しました。しばらく待ってから再試行してください。')
          } else if (parsed.detail) {
            setStatusMessage(parsed.detail)
          } else {
            setStatusMessage('音声合成に失敗しました。')
          }
        } catch {
          setStatusMessage('音声合成に失敗しました。')
        }
        setState('error')
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        setState('error')
        setStatusMessage('ストリームを受信できませんでした。')
        return
      }

      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split('\n\n')
        buffer = chunks.pop() ?? ''

        for (const chunk of chunks) {
          const trimmed = chunk.trim()
          if (!trimmed) continue
          const { event, payload } = parseSseChunk(trimmed)
          if (!payload) continue

          if (event === 'progress') {
            setStatusMessage((prev) => payload.message ?? prev)
          } else if (event === 'complete') {
            setState('success')
            setStatusMessage('音声が完成しました')
            router.refresh()
            return
          } else if (event === 'error') {
            setState('error')
            setStatusMessage(payload.message ?? 'エラーが発生しました。')
            return
          }
        }
      }
    } catch {
      setState('error')
      setStatusMessage('通信エラーが発生しました。')
    }
  }

  if (state === 'success') {
    return (
      <p className={compact ? 'text-xs text-emerald-600 font-medium' : 'text-sm text-emerald-600 font-medium'}>
        音声が完成しました
      </p>
    )
  }

  if (state === 'error') {
    return (
      <span className={compact ? 'inline-flex items-center gap-2 text-xs' : 'inline-flex items-center gap-3 text-sm'}>
        <span className="text-amber-600">{statusMessage}</span>
        <button
          type="button"
          onClick={handleClick}
          className="text-sky-600 underline hover:text-sky-700"
        >
          再試行
        </button>
      </span>
    )
  }

  if (state === 'loading') {
    return (
      <span className={compact ? 'inline-flex items-center gap-1.5 text-xs text-sky-600' : 'inline-flex items-center gap-2 text-sm text-sky-600'}>
        <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-sky-200 border-t-sky-600" />
        {statusMessage}
      </span>
    )
  }

  if (compact) {
    return (
      <button
        type="button"
        onClick={handleClick}
        className="inline-flex items-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 transition hover:bg-sky-100"
      >
        <svg className="h-3 w-3" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M3 8a5 5 0 1010 0A5 5 0 003 8z" stroke="currentColor" strokeWidth="1.5" />
          <path d="M6.5 6.5l3 1.5-3 1.5V6.5z" fill="currentColor" />
        </svg>
        音声を作成
      </button>
    )
  }

  return (
    <div className="flex flex-col items-center gap-3">
      <p className="text-sm text-slate-500">台本から音声を生成できます</p>
      <button
        type="button"
        onClick={handleClick}
        className="inline-flex items-center gap-2 rounded-2xl bg-sky-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-sky-700"
      >
        <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M3 8a5 5 0 1010 0A5 5 0 003 8z" stroke="currentColor" strokeWidth="1.5" />
          <path d="M6.5 6.5l3 1.5-3 1.5V6.5z" fill="currentColor" />
        </svg>
        音声ファイルを作成する
      </button>
    </div>
  )
}
