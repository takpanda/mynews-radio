'use client'

import { useRef, useState } from 'react'
import Link from 'next/link'
import {
  DASHBOARD_RANGES,
  failureReasonLabel,
  fetchDashboardStatsClient,
  formatMs,
  formatSuccessRate,
  type DashboardRange,
  type DashboardStats,
} from '../lib/admin-dashboard'
import { formatEventDateTime } from '../lib/admin-episode-logs'

const RANGE_LABELS: Record<DashboardRange, string> = { '7d': '7日', '30d': '30日' }
const EMPTY_TEXT = 'データなし'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <div className="mt-2">{children}</div>
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-1 text-xl font-semibold text-slate-900">{value}</dd>
    </div>
  )
}

export default function AdminDashboardShell({ initialData }: { initialData: DashboardStats }) {
  const [range, setRange] = useState<DashboardRange>(initialData.range ?? '7d')
  const [data, setData] = useState<DashboardStats>(initialData)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestId = useRef(0)

  const changeRange = async (next: DashboardRange) => {
    if (next === range || loading) return
    const id = ++requestId.current
    setLoading(true)
    setError(null)
    try {
      const stats = await fetchDashboardStatsClient(next)
      if (id !== requestId.current) return
      setData(stats)
      setRange(next)
    } catch {
      if (id !== requestId.current) return
      setError('集計の取得に失敗しました。しばらく後でもう一度お試しください。')
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }

  const { episodes, failures, llm, pending } = data
  const reasonEntries = Object.entries(failures.by_reason).filter(([, count]) => count > 0)
  const hasFailureBreakdown =
    reasonEntries.length > 0 || failures.llm_error_count > 0 || failures.episodes_without_phase_log > 0
  const durations = data.phase_durations.filter((d) => d.count > 0)

  return (
    <div aria-busy={loading}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-slate-900">運用ダッシュボード</h1>
        <div role="group" aria-label="集計期間" className="flex gap-1">
          {DASHBOARD_RANGES.map((r) => (
            <button
              key={r}
              type="button"
              disabled={loading}
              aria-pressed={range === r}
              onClick={() => changeRange(r)}
              className={`min-h-11 rounded-lg border px-4 text-sm ${
                range === r ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-white text-slate-700'
              }`}
            >
              {RANGE_LABELS[r]}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1 text-xs text-slate-500">直近{RANGE_LABELS[range]}の集計です。</p>
      {loading && <p className="mt-2 text-sm text-slate-500">読み込み中...</p>}
      {error && (
        <div role="alert" className="mt-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      <Section title="生成成功率">
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="成功率" value={formatSuccessRate(episodes.success_rate)} />
          <Stat label="完了" value={`${episodes.completed}件`} />
          <Stat label="失敗" value={`${episodes.failed}件`} />
          <Stat label="処理中・確認待ち" value={`${episodes.in_progress}件`} />
        </dl>
        {episodes.completed + episodes.failed === 0 && (
          <p className="mt-2 text-sm text-slate-400">{EMPTY_TEXT}</p>
        )}
      </Section>

      <Section title="対応待ち">
        <div className="grid gap-2 sm:grid-cols-2">
          <Link
            href="/admin/misreading-reports"
            className="flex min-h-11 items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm"
          >
            <span>未承認の読み間違い報告</span>
            <span className="font-semibold">{pending.unapproved_misreading_reports}件</span>
          </Link>
          <Link
            href="/admin/episodes"
            className="flex min-h-11 items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm"
          >
            <span>確認待ちの台本</span>
            <span className="font-semibold">{pending.awaiting_review_episodes}件</span>
          </Link>
        </div>
      </Section>

      <Section title="直近の失敗">
        {failures.recent.length === 0 ? (
          <p className="text-sm text-slate-400">直近の失敗はありません。</p>
        ) : (
          <ul className="space-y-2">
            {failures.recent.map((f, i) => (
              <li key={`${f.episode_id}-${f.occurred_at}-${i}`}>
                <Link
                  href={`/admin/episodes/${f.episode_id}/logs`}
                  className="flex min-h-11 flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm"
                >
                  <span className="text-xs text-slate-500">{formatEventDateTime(f.occurred_at)}</span>
                  <span className="font-medium text-slate-900">エピソード #{f.episode_id}</span>
                  <span className="text-red-700">
                    {failureReasonLabel(f.reason)}
                    {f.phase ? `（${f.phase}）` : ''}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="失敗内訳">
        {!hasFailureBreakdown ? (
          <p className="text-sm text-slate-400">{EMPTY_TEXT}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-slate-500">
                <th className="py-1 font-normal">理由</th>
                <th className="py-1 text-right font-normal">件数</th>
              </tr>
            </thead>
            <tbody>
              {reasonEntries.map(([reason, count]) => (
                <tr key={reason} className="border-b">
                  <td className="py-1">{failureReasonLabel(reason)}</td>
                  <td className="py-1 text-right">{count}</td>
                </tr>
              ))}
              <tr className="border-b">
                <td className="py-1">{failureReasonLabel('no_phase_log')}</td>
                <td className="py-1 text-right">{failures.episodes_without_phase_log}</td>
              </tr>
              <tr className="border-b">
                <td className="py-1">LLM呼び出しエラー</td>
                <td className="py-1 text-right">{failures.llm_error_count}</td>
              </tr>
            </tbody>
          </table>
        )}
      </Section>

      <Section title="音声合成フェーズ別の所要時間">
        {durations.length === 0 ? (
          <p className="text-sm text-slate-400">{EMPTY_TEXT}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-slate-500">
                  <th className="py-1 font-normal">フェーズ</th>
                  <th className="py-1 text-right font-normal">件数</th>
                  <th className="py-1 text-right font-normal">平均</th>
                  <th className="py-1 text-right font-normal">最大</th>
                </tr>
              </thead>
              <tbody>
                {durations.map((d) => (
                  <tr key={d.phase} className="border-b">
                    <td className="py-1">{d.phase}</td>
                    <td className="py-1 text-right">{d.count}</td>
                    <td className="py-1 text-right">{formatMs(d.avg_ms)}</td>
                    <td className="py-1 text-right">{formatMs(d.max_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="LLM">
        <dl className="grid grid-cols-2 gap-2">
          <Stat label="リトライ" value={`${llm.retry_count}件`} />
          <Stat label="JSONパース失敗" value={`${llm.json_parse_failed_count}件`} />
        </dl>
        {llm.latency_by_phase.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">{EMPTY_TEXT}</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-slate-500">
                  <th className="py-1 font-normal">フェーズ</th>
                  <th className="py-1 text-right font-normal">件数</th>
                  <th className="py-1 text-right font-normal">平均レイテンシ</th>
                  <th className="py-1 text-right font-normal">最大レイテンシ</th>
                </tr>
              </thead>
              <tbody>
                {llm.latency_by_phase.map((l) => (
                  <tr key={l.phase} className="border-b">
                    <td className="py-1">{l.phase}</td>
                    <td className="py-1 text-right">{l.call_count}</td>
                    <td className="py-1 text-right">{formatMs(l.avg_latency_ms)}</td>
                    <td className="py-1 text-right">{formatMs(l.max_latency_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  )
}
