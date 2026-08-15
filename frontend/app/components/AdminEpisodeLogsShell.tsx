'use client'

import { useCallback, useMemo, useState } from 'react'
import Link from 'next/link'
import type {
  AdminEpisodeLogs,
  AdminEpisodeLogsTimelineEvent,
} from '../lib/admin-episode-logs'
import {
  fetchAdminEpisodeLogsClient,
  formatDurationMs,
  formatEventDateTime,
  formatSeconds,
  phaseLabel,
  resultLabel,
  resultToneClassName,
} from '../lib/admin-episode-logs'

interface Props {
  episodeId: number
  initialData: AdminEpisodeLogs
}

interface SynthAttempt {
  phaseLogId: number
  attemptNo: number
  result: string | null
}

function synthAttemptsFromTimeline(timeline: AdminEpisodeLogsTimelineEvent[]): SynthAttempt[] {
  return timeline
    .filter((event) => event.source === 'phase' && event.phase === 'synthesize')
    .map((event) => ({
      phaseLogId: event.source_id,
      attemptNo: event.attempt_no ?? 0,
      result: event.result,
    }))
    .sort((a, b) => b.attemptNo - a.attemptNo)
}

function sortedTimeline(timeline: AdminEpisodeLogsTimelineEvent[]): AdminEpisodeLogsTimelineEvent[] {
  return [...timeline].sort((a, b) => {
    const aTime = a.occurred_at ?? ''
    const bTime = b.occurred_at ?? ''
    if (aTime !== bTime) return aTime < bTime ? -1 : 1
    const aRank = a.source === 'audit' ? 0 : 1
    const bRank = b.source === 'audit' ? 0 : 1
    if (aRank !== bRank) return aRank - bRank
    return a.source_id - b.source_id
  })
}

function ResultBadge({ result }: { result: string | null }) {
  const label = resultLabel(result)
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold ${resultToneClassName(label.tone)}`}>
      <span aria-hidden="true">{label.icon}</span>
      {label.text}
    </span>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-slate-400">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-slate-700">{value}</dd>
    </div>
  )
}

export default function AdminEpisodeLogsShell({ episodeId, initialData }: Props) {
  const [data, setData] = useState<AdminEpisodeLogs>(initialData)
  const initialAttempts = useMemo(() => synthAttemptsFromTimeline(initialData.timeline), [initialData])
  const [selectedPhaseLogId, setSelectedPhaseLogId] = useState<number | null>(
    initialData.lines[0]?.phase_log_id ?? initialAttempts[0]?.phaseLogId ?? null,
  )
  const [switching, setSwitching] = useState(false)
  const [switchError, setSwitchError] = useState<string | null>(null)

  const attempts = useMemo(() => synthAttemptsFromTimeline(data.timeline), [data])
  const timeline = useMemo(() => sortedTimeline(data.timeline), [data])

  const handleSelectAttempt = useCallback(
    async (phaseLogId: number) => {
      if (phaseLogId === selectedPhaseLogId || switching) return
      setSwitching(true)
      setSwitchError(null)
      try {
        const next = await fetchAdminEpisodeLogsClient(episodeId, phaseLogId)
        setData(next)
        setSelectedPhaseLogId(phaseLogId)
      } catch {
        setSwitchError('過去の試行の取得に失敗しました。もう一度お試しください。')
      } finally {
        setSwitching(false)
      }
    },
    [episodeId, selectedPhaseLogId, switching],
  )

  const latestAttemptNo = attempts[0]?.attemptNo

  return (
    <div className="space-y-5">
      {/* ヘッダー */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <Link
          href={`/episodes/${episodeId}`}
          className="inline-flex items-center gap-1.5 text-xs text-slate-500 transition hover:text-slate-900"
        >
          <span aria-hidden="true">←</span>
          公開ページへ戻る
        </Link>
        <h1 className="mt-2 text-lg font-semibold text-slate-900">生成詳細ログ</h1>
        <p className="mt-1 text-sm text-slate-500">
          エピソード #{data.episode.id} の受付から完了・失敗までの経過を確認できます。
        </p>
      </div>

      {/* エピソード概要 */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold text-slate-900">エピソード概要</h2>
        <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="ID" value={String(data.episode.id)} />
          <Field label="日付" value={data.episode.episode_date} />
          <Field label="回号" value={String(data.episode.seq)} />
          <Field label="種別" value={data.episode.type} />
          <Field label="状態" value={data.episode.status} />
          <Field label="作成日時" value={formatEventDateTime(data.episode.created_at)} />
          <Field label="更新日時" value={formatEventDateTime(data.episode.updated_at)} />
        </dl>
      </section>

      {/* 生成ジョブ */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold text-slate-900">生成ジョブ</h2>
        {data.generation_jobs.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">生成ジョブの記録はありません。</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {data.generation_jobs.map((job) => (
              <li key={job.id} className="rounded-xl border border-slate-100 p-3">
                <dl className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                  <Field label="操作" value={job.operation} />
                  <Field label="担当者" value={job.owner.username} />
                  <Field label="状態" value={job.status} />
                  <Field label="IPアドレス(ハッシュ)" value={job.client_ip_hash ?? '—'} />
                  <Field label="受付日時" value={formatEventDateTime(job.claimed_at)} />
                  <Field label="完了日時" value={formatEventDateTime(job.finished_at)} />
                </dl>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* タイムライン */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold text-slate-900">タイムライン</h2>
        {timeline.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">ログがありません。</p>
        ) : (
          <ol className="mt-3 space-y-3">
            {timeline.map((event) => (
              <li key={`${event.source}-${event.source_id}`} className="rounded-xl border border-slate-100 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-900">
                    {event.source === 'phase'
                      ? `${phaseLabel(event.phase)}${event.attempt_no ? `（試行${event.attempt_no}）` : ''}`
                      : `操作: ${event.operation ?? '不明'}`}
                  </span>
                  <ResultBadge result={event.result} />
                </div>
                <dl className="mt-2 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                  <Field label="開始時刻" value={formatEventDateTime(event.started_at ?? event.occurred_at)} />
                  <Field label="終了時刻" value={formatEventDateTime(event.ended_at)} />
                  <Field label="所要時間" value={formatDurationMs(event.duration_ms)} />
                  {event.tts_engine && <Field label="TTSエンジン" value={event.tts_engine} />}
                  {event.line_total_count !== null && event.line_total_count !== undefined && (
                    <Field
                      label="行の成功数"
                      value={`${event.line_success_count ?? 0} / ${event.line_total_count}`}
                    />
                  )}
                </dl>
                {event.reason && (
                  <p className="mt-2 flex items-start gap-1.5 text-xs text-rose-700">
                    <span aria-hidden="true">⚠</span>
                    <span className="break-words">理由: {event.reason}</span>
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      {/* 行単位の詳細 */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-900">行単位の詳細（音声合成）</h2>
          {switching && <span className="text-xs text-slate-400">読み込み中...</span>}
        </div>

        {attempts.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="音声合成試行の選択">
            {attempts.map((attempt) => {
              const isSelected = attempt.phaseLogId === selectedPhaseLogId
              return (
                <button
                  key={attempt.phaseLogId}
                  type="button"
                  onClick={() => handleSelectAttempt(attempt.phaseLogId)}
                  disabled={switching}
                  aria-pressed={isSelected}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${
                    isSelected
                      ? 'border-slate-900 bg-slate-900 text-white'
                      : 'border-slate-200 text-slate-600 hover:border-slate-300'
                  }`}
                >
                  試行{attempt.attemptNo}
                  {attempt.attemptNo === latestAttemptNo ? '（最新）' : ''}
                </button>
              )
            })}
          </div>
        )}

        {switchError && (
          <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">
            {switchError}
          </div>
        )}

        {selectedPhaseLogId === null ? (
          <p className="mt-3 text-sm text-slate-400">行ログはありません。</p>
        ) : data.lines.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">この試行の行ログはありません。</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {data.lines.map((line) => (
              <li key={`${line.phase_log_id}-${line.script_line_index}`} className="rounded-xl border border-slate-100 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-900">行 {line.script_line_index}</span>
                  <ResultBadge result={line.synth_result} />
                </div>
                <dl className="mt-2 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                  <Field label="記事ID" value={line.article_id !== null ? String(line.article_id) : '—'} />
                  <Field label="話者" value={line.speaker ?? '—'} />
                  <Field label="セクション" value={line.section ?? '—'} />
                  <Field label="話速設定" value={line.delivery ?? '—'} />
                  <Field label="TTSエンジン" value={line.tts_engine ?? '—'} />
                  <Field label="実際の話速" value={line.speaking_rate !== null ? line.speaking_rate.toFixed(2) : '—'} />
                  <Field label="処理時間" value={formatDurationMs(line.processing_duration_ms)} />
                  <Field label="無音時間" value={formatSeconds(line.silence_before_sec)} />
                  <Field label="開始位置" value={formatSeconds(line.start_time_sec)} />
                  <Field label="リトライ回数" value={String(line.retry_count)} />
                  <Field label="音声ファイル" value={line.wav_file ?? '—'} />
                </dl>
                {line.failure_reason && (
                  <p className="mt-2 flex items-start gap-1.5 text-xs text-rose-700">
                    <span aria-hidden="true">⚠</span>
                    <span className="break-words">失敗理由: {line.failure_reason}</span>
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
