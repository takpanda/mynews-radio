"use client"

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { generateEpisodeStream } from '../lib/api'

function parseSseChunk(chunk: string) {
  const lines = chunk.split('\n')
  const eventLine = lines.find((line) => line.startsWith('event:'))
  const dataLines = lines.filter((line) => line.startsWith('data:'))
  const event = eventLine ? eventLine.slice('event:'.length).trim() : 'message'
  const data = dataLines.map((line) => line.slice('data:'.length)).join('\n')

  try {
    return { event, payload: JSON.parse(data) }
  } catch {
    return { event, payload: null }
  }
}

export default function GenerateEpisodeButton() {
  const [isLoading, setIsLoading] = useState(false)
  const [progress, setProgress] = useState<string[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [newsSource, setNewsSource] = useState<'hatena_bookmark' | 'hatena_hotentry_all'>('hatena_bookmark')
  const [ttsEngine, setTtsEngine] = useState<'voicevox' | 'aivispeech'>('voicevox')
  const router = useRouter()

  const appendProgress = (text: string) => {
    setProgress((current) => [...current, text])
  }

  const handleClick = async () => {
    setIsLoading(true)
    setProgress([])
    setMessage(null)

    try {
      const today = new Date().toISOString().slice(0, 10)
      const response = await generateEpisodeStream(today, 10, newsSource, ttsEngine)

      if (!response.ok) {
        const errorText = await response.text().catch(() => '')
        setMessage(errorText || '番組生成に失敗しました。')
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        setMessage('ストリームを受信できませんでした。')
        return
      }

      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let isCompleted = false

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
            appendProgress(payload.message ?? '進捗更新')
          } else if (event === 'complete') {
            setMessage(payload.message ?? '生成が完了しました。')
            isCompleted = true
          } else if (event === 'error') {
            setMessage(payload.message ?? 'エラーが発生しました。')
            isCompleted = true
          }
        }

        if (isCompleted) {
          break
        }
      }

      if (isCompleted) {
        router.refresh()
      }
    } catch (error) {
      setMessage('通信エラーが発生しました。後でもう一度お試しください。')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="mb-6 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex gap-4 text-sm">
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="radio"
            name="newsSource"
            value="hatena_bookmark"
            checked={newsSource === 'hatena_bookmark'}
            onChange={() => setNewsSource('hatena_bookmark')}
            disabled={isLoading}
            className="accent-blue-600"
          />
          <span>テックニュース</span>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="radio"
            name="newsSource"
            value="hatena_hotentry_all"
            checked={newsSource === 'hatena_hotentry_all'}
            onChange={() => setNewsSource('hatena_hotentry_all')}
            disabled={isLoading}
            className="accent-blue-600"
          />
          <span>一般ニュース</span>
        </label>
      </div>
      <div className="mb-3 flex gap-4 text-sm">
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="radio"
            name="ttsEngine"
            value="voicevox"
            checked={ttsEngine === 'voicevox'}
            onChange={() => setTtsEngine('voicevox')}
            disabled={isLoading}
            className="accent-blue-600"
          />
          <span>VOICEVOX</span>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="radio"
            name="ttsEngine"
            value="aivispeech"
            checked={ttsEngine === 'aivispeech'}
            onChange={() => setTtsEngine('aivispeech')}
            disabled={isLoading}
            className="accent-blue-600"
          />
          <span>AivisSpeech</span>
        </label>
      </div>
      <button
        type="button"
        onClick={handleClick}
        disabled={isLoading}
        className="inline-flex items-center justify-center rounded-2xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-400"
      >
        {isLoading ? '生成中…' : '記事生成を実行する'}
      </button>

      {progress.length > 0 && (
        <div className="mt-4 space-y-2 text-sm text-gray-700">
          {progress.map((line, index) => (
            <div key={index} className="rounded-xl bg-slate-50 p-3">
              {line}
            </div>
          ))}
        </div>
      )}

      {message ? (
        <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm text-gray-800">
          {message}
        </div>
      ) : null}
    </div>
  )
}
