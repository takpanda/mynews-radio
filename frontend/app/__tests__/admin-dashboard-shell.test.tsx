import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminDashboardShell from '../components/AdminDashboardShell'
import type { DashboardStats } from '../lib/admin-dashboard'

const mockFetchClient = jest.fn()
jest.mock('../lib/admin-dashboard', () => {
  const actual = jest.requireActual('../lib/admin-dashboard')
  return { ...actual, fetchDashboardStatsClient: (...args: unknown[]) => mockFetchClient(...args) }
})

const baseStats: DashboardStats = {
  range: '7d',
  since: '2026-11-13T00:00:00+00:00',
  generated_at: '2026-11-20T00:00:00+00:00',
  episodes: { completed: 2, failed: 1, in_progress: 3, success_rate: 2 / 3 },
  phase_durations: [
    { phase: 'synthesize', count: 3, avg_ms: 1234.5, max_ms: 5000 },
    { phase: 'wav_combine', count: 0, avg_ms: null, max_ms: null },
    { phase: 'mp3_encode', count: 0, avg_ms: null, max_ms: null },
  ],
  failures: {
    by_reason: {
      script_missing: 0,
      tts_no_lines_succeeded: 0,
      tts_synthesis_exception: 0,
      wav_combine_failed: 0,
      mp3_encode_failed: 0,
      build_exception: 1,
    },
    llm_error_count: 2,
    episodes_without_phase_log: 1,
    recent: [
      { occurred_at: '2026-11-19T01:00:00+00:00', episode_id: 11, phase: 'synthesize', reason: 'build_exception' },
      { occurred_at: '2026-11-18T01:00:00+00:00', episode_id: 12, phase: null, reason: 'no_phase_log' },
    ],
  },
  llm: {
    latency_by_phase: [{ phase: 'script', call_count: 4, avg_latency_ms: 800, max_latency_ms: 2000 }],
    retry_count: 2,
    json_parse_failed_count: 1,
    anomalies_by_phase: [{ phase: 'script', retry_count: 2, json_parse_failed_count: 1 }],
  },
  pending: { unapproved_misreading_reports: 5, awaiting_review_episodes: 2 },
}

const emptyStats: DashboardStats = {
  ...baseStats,
  episodes: { completed: 0, failed: 0, in_progress: 0, success_rate: null },
  phase_durations: baseStats.phase_durations.map((d) => ({ ...d, count: 0, avg_ms: null, max_ms: null })),
  failures: {
    by_reason: Object.fromEntries(Object.keys(baseStats.failures.by_reason).map((k) => [k, 0])),
    llm_error_count: 0,
    episodes_without_phase_log: 0,
    recent: [],
  },
  llm: { latency_by_phase: [], retry_count: 0, json_parse_failed_count: 0, anomalies_by_phase: [] },
  pending: { unapproved_misreading_reports: 0, awaiting_review_episodes: 0 },
}

beforeEach(() => mockFetchClient.mockReset())

describe('AdminDashboardShell', () => {
  it('正常系：成功率・件数・失敗一覧・導線が表示される', () => {
    render(<AdminDashboardShell initialData={baseStats} />)
    expect(screen.getByText('66.7%')).toBeInTheDocument()
    expect(screen.getByText('完了')).toBeInTheDocument()
    expect(screen.getByText('処理中・確認待ち')).toBeInTheDocument()
    expect(screen.getByText('1,235 ms')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /エピソード #11/ })).toHaveAttribute('href', '/admin/episodes/11/logs')
    expect(screen.getByRole('link', { name: /未承認の読み間違い報告/ })).toHaveAttribute('href', '/admin/misreading-reports')
    expect(screen.getByRole('link', { name: /確認待ちの台本/ })).toHaveAttribute('href', '/admin/episodes')
    expect(screen.getByText('LLM呼び出しエラー')).toBeInTheDocument()
  })

  it('phase が null の失敗は「音声合成前の失敗」と表示され、画面が壊れない', () => {
    render(<AdminDashboardShell initialData={baseStats} />)
    const link = screen.getByRole('link', { name: /エピソード #12/ })
    expect(link).toHaveTextContent('音声合成前の失敗')
    expect(link).toHaveAttribute('href', '/admin/episodes/12/logs')
  })

  it('音声合成前の失敗だけの場合も一覧に表示される', () => {
    const stats: DashboardStats = {
      ...emptyStats,
      episodes: { completed: 0, failed: 1, in_progress: 0, success_rate: 0 },
      failures: {
        ...emptyStats.failures,
        episodes_without_phase_log: 1,
        recent: [{ occurred_at: '2026-11-18T01:00:00+00:00', episode_id: 7, phase: null, reason: 'no_phase_log' }],
      },
    }
    render(<AdminDashboardShell initialData={stats} />)
    expect(screen.getByRole('link', { name: /エピソード #7/ })).toHaveTextContent('音声合成前の失敗')
    expect(screen.getByText('0%')).toBeInTheDocument()
  })

  it('0件：成功率は「—」、各セクションは「データなし」と表示される', () => {
    render(<AdminDashboardShell initialData={emptyStats} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.getAllByText('データなし').length).toBeGreaterThanOrEqual(4)
    expect(screen.getByText('直近の失敗はありません。')).toBeInTheDocument()
  })

  it('30日に切り替えるとプロキシへ range=30d で取得し表示が更新される', async () => {
    mockFetchClient.mockResolvedValueOnce({
      ...baseStats,
      range: '30d',
      episodes: { completed: 9, failed: 1, in_progress: 0, success_rate: 0.9 },
    })
    const user = userEvent.setup()
    render(<AdminDashboardShell initialData={baseStats} />)
    await user.click(screen.getByRole('button', { name: '30日' }))
    await waitFor(() => expect(screen.getByText('90%')).toBeInTheDocument())
    expect(mockFetchClient).toHaveBeenCalledWith('30d')
    expect(screen.getByRole('button', { name: '30日' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('切替でAPIエラーの場合はエラーを表示し、直前の表示を維持する', async () => {
    mockFetchClient.mockRejectedValueOnce(new Error('boom'))
    const user = userEvent.setup()
    render(<AdminDashboardShell initialData={baseStats} />)
    await user.click(screen.getByRole('button', { name: '30日' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('集計の取得に失敗しました')
    expect(screen.getByText('66.7%')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '7日' })).toHaveAttribute('aria-pressed', 'true')
  })
})
