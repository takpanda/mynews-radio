'use client'

import { useRef, useState } from 'react'
import FemaleMcCandidateFormModal from './FemaleMcCandidateFormModal'
import {
  updateFemaleMcCandidateClient,
  type FemaleMcCandidate,
} from '../lib/admin-female-mc-candidates'

interface Props {
  initialData: FemaleMcCandidate[]
}

export default function FemaleMcCandidatesPanel({ initialData }: Props) {
  const [candidates, setCandidates] = useState<FemaleMcCandidate[]>(initialData)
  const [playingVoice, setPlayingVoice] = useState<string | null>(null)
  const [playErrors, setPlayErrors] = useState<Record<string, string | null>>({})
  const [togglingVoices, setTogglingVoices] = useState<Set<string>>(new Set())
  const [toggleErrors, setToggleErrors] = useState<Record<string, string | null>>({})
  const [modalOpen, setModalOpen] = useState(false)
  const [editingCandidate, setEditingCandidate] = useState<FemaleMcCandidate | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const handleTogglePlay = (candidate: FemaleMcCandidate) => {
    const audio = audioRef.current
    if (!audio || !candidate.sample.available) return
    if (playingVoice === candidate.voice_name) {
      audio.pause()
      audio.currentTime = 0
      setPlayingVoice(null)
      return
    }
    setPlayErrors((prev) => ({ ...prev, [candidate.voice_name]: null }))
    audio.src = candidate.sample.url
    setPlayingVoice(candidate.voice_name)
    audio.play().catch(() => {
      setPlayErrors((prev) => ({ ...prev, [candidate.voice_name]: 'サンプルを再生できませんでした' }))
      setPlayingVoice(null)
    })
  }

  const handleToggleActive = async (candidate: FemaleMcCandidate) => {
    if (togglingVoices.has(candidate.voice_name)) return
    setTogglingVoices((prev) => new Set(prev).add(candidate.voice_name))
    setToggleErrors((prev) => ({ ...prev, [candidate.voice_name]: null }))
    try {
      const updated = await updateFemaleMcCandidateClient(candidate.voice_name, {
        is_active: !candidate.is_active,
      })
      setCandidates((prev) => prev.map((c) => (c.voice_name === updated.voice_name ? updated : c)))
    } catch (err) {
      setToggleErrors((prev) => ({
        ...prev,
        [candidate.voice_name]: err instanceof Error ? err.message : '更新できませんでした',
      }))
    } finally {
      setTogglingVoices((prev) => {
        const next = new Set(prev)
        next.delete(candidate.voice_name)
        return next
      })
    }
  }

  const handleAdd = () => {
    setEditingCandidate(null)
    setModalOpen(true)
  }

  const handleEdit = (candidate: FemaleMcCandidate) => {
    setEditingCandidate(candidate)
    setModalOpen(true)
  }

  const handleModalClose = () => {
    setModalOpen(false)
    setEditingCandidate(null)
  }

  const handleModalSuccess = (saved: FemaleMcCandidate) => {
    setCandidates((prev) => {
      const exists = prev.some((c) => c.voice_name === saved.voice_name)
      return exists ? prev.map((c) => (c.voice_name === saved.voice_name ? saved : c)) : [...prev, saved]
    })
    handleModalClose()
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">女性MC候補マスタ</h2>
          <p className="mt-1 text-xs text-slate-500">
            候補を追加・編集し、有効/無効を切り替えます。無効な候補はカテゴリ別設定の選択肢に表示されません。
          </p>
        </div>
        <button
          type="button"
          onClick={handleAdd}
          className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700"
        >
          候補を追加
        </button>
      </div>

      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio
        ref={audioRef}
        onEnded={() => setPlayingVoice(null)}
        onError={() => {
          setPlayingVoice((current) => {
            if (current) {
              setPlayErrors((prev) => ({ ...prev, [current]: 'サンプルを再生できませんでした' }))
            }
            return null
          })
        }}
        className="hidden"
      />

      {candidates.length === 0 ? (
        <p className="mt-4 text-sm text-slate-400">候補がまだありません。「候補を追加」から追加してください。</p>
      ) : (
        <div className="mt-3 divide-y divide-slate-100">
          {candidates.map((candidate) => {
            const isPlaying = playingVoice === candidate.voice_name
            const playError = playErrors[candidate.voice_name]
            const toggleError = toggleErrors[candidate.voice_name]
            const toggling = togglingVoices.has(candidate.voice_name)
            return (
              <div key={candidate.voice_name} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-slate-900">{candidate.display_name}</p>
                    <span
                      className={`inline-flex items-center gap-1 text-xs font-medium ${
                        candidate.is_active ? 'text-emerald-700' : 'text-slate-400'
                      }`}
                    >
                      <span
                        className={`h-2 w-2 rounded-full ${candidate.is_active ? 'bg-emerald-500' : 'bg-slate-300'}`}
                      />
                      {candidate.is_active ? '有効' : '無効'}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-slate-500">{candidate.voice_name}</p>
                  <p className="mt-0.5 truncate text-xs text-slate-400">{candidate.sample_text}</p>
                  {!candidate.sample.available && (
                    <p className="mt-1 text-xs text-amber-600">サンプル音声が未登録です</p>
                  )}
                  {playError && (
                    <p role="alert" className="mt-1 text-xs text-rose-600">
                      {playError}
                    </p>
                  )}
                  {toggleError && (
                    <p role="alert" className="mt-1 text-xs text-rose-600">
                      {toggleError}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleTogglePlay(candidate)}
                    disabled={!candidate.sample.available}
                    aria-label={`${candidate.display_name}のサンプルを${isPlaying ? '停止' : '再生'}`}
                    className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isPlaying ? '停止' : '再生'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleEdit(candidate)}
                    className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
                  >
                    編集
                  </button>
                  <button
                    type="button"
                    onClick={() => handleToggleActive(candidate)}
                    disabled={toggling}
                    role="switch"
                    aria-checked={candidate.is_active}
                    aria-label={
                      candidate.is_active
                        ? `${candidate.display_name}を無効にする`
                        : `${candidate.display_name}を有効にする`
                    }
                    className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span
                      className={`inline-block h-5 w-9 rounded-full transition-colors ${
                        candidate.is_active ? 'bg-emerald-500' : 'bg-slate-300'
                      }`}
                    />
                    <span
                      className={`absolute left-0.5 inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
                        candidate.is_active ? 'translate-x-4' : 'translate-x-0.5'
                      }`}
                    />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {modalOpen && (
        <FemaleMcCandidateFormModal
          candidate={editingCandidate}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      )}
    </div>
  )
}
