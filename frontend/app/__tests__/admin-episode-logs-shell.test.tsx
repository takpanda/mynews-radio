import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminEpisodeLogsShell from '../components/AdminEpisodeLogsShell'
import type { AdminEpisodeLogs } from '../lib/admin-episode-logs'

const mockFetchClient = jest.fn()
const mockFetchLlmCallClient = jest.fn()
jest.mock('../lib/admin-episode-logs', () => {
  const actual = jest.requireActual('../lib/admin-episode-logs')
  return {
    ...actual,
    fetchAdminEpisodeLogsClient: (...args: unknown[]) => mockFetchClient(...args),
    fetchAdminEpisodeLlmCallClient: (...args: unknown[]) => mockFetchLlmCallClient(...args),
  }
})

function baseData(overrides: Partial<AdminEpisodeLogs> = {}): AdminEpisodeLogs {
  return {
    episode: {
      id: 7, episode_date: '2026-08-14', seq: 1, status: 'completed', type: 'daily',
      created_at: '2026-08-14T10:00:00+00:00', updated_at: '2026-08-14T10:05:00+00:00',
    },
    generation_jobs: [],
    timeline: [],
    llm_calls: [],
    lines: [],
    ...overrides,
  }
}

describe('AdminEpisodeLogsShell 概要', () => {
  it('エピソード概要を表示する', () => {
    render(<AdminEpisodeLogsShell episodeId={7} initialData={baseData()} />)
    expect(screen.getByText('生成詳細ログ')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('2026-08-14')).toBeInTheDocument()
    expect(screen.getByText('completed')).toBeInTheDocument()
  })
})

describe('AdminEpisodeLogsShell 生成ジョブ', () => {
  it('ジョブがない場合は専用メッセージを表示する', () => {
    render(<AdminEpisodeLogsShell episodeId={7} initialData={baseData()} />)
    expect(screen.getByText('生成ジョブの記録はありません。')).toBeInTheDocument()
  })

  it('ジョブがある場合は担当者・IPハッシュ・状態を表示する', () => {
    const data = baseData({
      generation_jobs: [{
        id: 1, operation: 'generate', owner: { id: 1, username: 'owner-name' },
        client_ip_hash: 'sha256-hash-abc', status: 'completed',
        claimed_at: '2026-08-14T10:00:00+00:00', finished_at: '2026-08-14T10:03:00+00:00',
      }],
    })
    render(<AdminEpisodeLogsShell episodeId={7} initialData={data} />)
    expect(screen.getByText('owner-name')).toBeInTheDocument()
    expect(screen.getByText('sha256-hash-abc')).toBeInTheDocument()
  })
})

describe('AdminEpisodeLogsShell タイムライン', () => {
  it('ログがない場合は専用メッセージを表示する', () => {
    render(<AdminEpisodeLogsShell episodeId={7} initialData={baseData()} />)
    expect(screen.getByText('ログがありません。')).toBeInTheDocument()
  })

  it('synthesize/wav_combine/mp3_encode を区別して表示し、古い順に並ぶ', () => {
    const data = baseData({
      timeline: [
        {
          source: 'phase', source_id: 2, generation_job_id: 1, operation: null,
          phase: 'wav_combine', attempt_no: 1, result: 'success',
          occurred_at: '2026-08-14T10:02:00+00:00', started_at: '2026-08-14T10:02:00+00:00',
          ended_at: '2026-08-14T10:02:10+00:00', duration_ms: 10000, reason: null,
          tts_engine: null, line_success_count: null, line_total_count: null,
        },
        {
          source: 'phase', source_id: 1, generation_job_id: 1, operation: null,
          phase: 'synthesize', attempt_no: 1, result: 'success',
          occurred_at: '2026-08-14T10:00:00+00:00', started_at: '2026-08-14T10:00:00+00:00',
          ended_at: '2026-08-14T10:01:50+00:00', duration_ms: 110000, reason: null,
          tts_engine: 'voicevox', line_success_count: 1, line_total_count: 1,
        },
        {
          source: 'phase', source_id: 3, generation_job_id: 1, operation: null,
          phase: 'mp3_encode', attempt_no: 1, result: 'failure',
          occurred_at: '2026-08-14T10:03:00+00:00', started_at: '2026-08-14T10:03:00+00:00',
          ended_at: '2026-08-14T10:03:05+00:00', duration_ms: 5000, reason: 'mp3_encode_failed',
          tts_engine: null, line_success_count: null, line_total_count: null,
        },
      ],
    })
    render(<AdminEpisodeLogsShell episodeId={7} initialData={data} />)

    const items = screen.getAllByRole('listitem').filter((el) =>
      ['音声合成', '音声結合', 'MP3エンコード'].some((label) => el.textContent?.includes(label)),
    )
    const order = items.map((el) => el.textContent ?? '')
    expect(order[0]).toContain('音声合成')
    expect(order[1]).toContain('音声結合')
    expect(order[2]).toContain('MP3エンコード')

    // 失敗は色だけでなく文字とアイコンで識別できる
    expect(screen.getByText('mp3_encode_failed', { exact: false })).toBeInTheDocument()
    const failureBadges = screen.getAllByText('失敗')
    expect(failureBadges.length).toBeGreaterThan(0)
    expect(screen.getAllByText('✕').length).toBeGreaterThan(0)
  })
})

describe('AdminEpisodeLogsShell 行単位の詳細', () => {
  it('合成試行がない場合は専用メッセージを表示する', () => {
    render(<AdminEpisodeLogsShell episodeId={7} initialData={baseData()} />)
    expect(screen.getByText('行ログはありません。')).toBeInTheDocument()
  })

  it('最新試行の行ログを初期表示し、失敗理由を文字で示す', () => {
    const data = baseData({
      timeline: [{
        source: 'phase', source_id: 10, generation_job_id: 1, operation: null,
        phase: 'synthesize', attempt_no: 1, result: 'failure',
        occurred_at: '2026-08-14T10:00:00+00:00', started_at: '2026-08-14T10:00:00+00:00',
        ended_at: '2026-08-14T10:00:05+00:00', duration_ms: 5000, reason: null,
        tts_engine: 'voicevox', line_success_count: 0, line_total_count: 1,
      }],
      lines: [{
        phase_log_id: 10, attempt_no: 1, script_line_index: 1, article_id: null,
        speaker: 'male', section: 'intro', delivery: 'neutral', tts_engine: 'voicevox',
        speaking_rate: 1.0, processing_duration_ms: 850, synth_result: 'failure',
        retry_count: 2, wav_file: null, silence_before_sec: 0, start_time_sec: null,
        failure_reason: 'tts_request_failed',
      }],
    })
    render(<AdminEpisodeLogsShell episodeId={7} initialData={data} />)
    expect(screen.getByText('行 1')).toBeInTheDocument()
    expect(screen.getByText(/失敗理由: tts_request_failed/)).toBeInTheDocument()
  })

  it('wav_fileがAPI応答に含まれていても画面に表示しない', () => {
    const leakedPath = '/private/audio/output-001.wav'
    const data = baseData({
      timeline: [{
        source: 'phase', source_id: 10, generation_job_id: 1, operation: null,
        phase: 'synthesize', attempt_no: 1, result: 'success',
        occurred_at: '2026-08-14T10:00:00+00:00', started_at: '2026-08-14T10:00:00+00:00',
        ended_at: '2026-08-14T10:00:05+00:00', duration_ms: 5000, reason: null,
        tts_engine: 'voicevox', line_success_count: 1, line_total_count: 1,
      }],
      lines: [{
        phase_log_id: 10, attempt_no: 1, script_line_index: 1, article_id: null,
        speaker: 'male', section: 'intro', delivery: 'neutral', tts_engine: 'voicevox',
        speaking_rate: 1.0, processing_duration_ms: 850, synth_result: 'success',
        retry_count: 0, wav_file: leakedPath, silence_before_sec: 0, start_time_sec: 1.2,
        failure_reason: null,
      }],
    })
    render(<AdminEpisodeLogsShell episodeId={7} initialData={data} />)
    expect(screen.getByText('行 1')).toBeInTheDocument()
    expect(screen.queryByText(leakedPath)).not.toBeInTheDocument()
    expect(screen.queryByText('音声ファイル')).not.toBeInTheDocument()
  })

  it('過去の試行を選択すると該当行を再取得して表示する', async () => {
    const user = userEvent.setup()
    const data = baseData({
      timeline: [
        {
          source: 'phase', source_id: 20, generation_job_id: 1, operation: null,
          phase: 'synthesize', attempt_no: 2, result: 'success',
          occurred_at: '2026-08-14T10:05:00+00:00', started_at: '2026-08-14T10:05:00+00:00',
          ended_at: '2026-08-14T10:05:05+00:00', duration_ms: 5000, reason: null,
          tts_engine: 'voicevox', line_success_count: 1, line_total_count: 1,
        },
        {
          source: 'phase', source_id: 10, generation_job_id: 1, operation: null,
          phase: 'synthesize', attempt_no: 1, result: 'failure',
          occurred_at: '2026-08-14T10:00:00+00:00', started_at: '2026-08-14T10:00:00+00:00',
          ended_at: '2026-08-14T10:00:05+00:00', duration_ms: 5000, reason: null,
          tts_engine: 'voicevox', line_success_count: 0, line_total_count: 1,
        },
      ],
      lines: [{
        phase_log_id: 20, attempt_no: 2, script_line_index: 1, article_id: null,
        speaker: 'male', section: 'intro', delivery: 'neutral', tts_engine: 'voicevox',
        speaking_rate: 1.0, processing_duration_ms: 700, synth_result: 'success',
        retry_count: 0, wav_file: '001.wav', silence_before_sec: 0, start_time_sec: 1.2,
        failure_reason: null,
      }],
    })

    mockFetchClient.mockResolvedValueOnce({
      ...data,
      lines: [{
        phase_log_id: 10, attempt_no: 1, script_line_index: 1, article_id: null,
        speaker: 'male', section: 'intro', delivery: 'neutral', tts_engine: 'voicevox',
        speaking_rate: 1.0, processing_duration_ms: 850, synth_result: 'failure',
        retry_count: 2, wav_file: null, silence_before_sec: 0, start_time_sec: null,
        failure_reason: 'tts_request_failed',
      }],
    })

    render(<AdminEpisodeLogsShell episodeId={7} initialData={data} />)
    expect(screen.getByRole('button', { name: '試行2（最新）' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: '試行1' }))

    expect(mockFetchClient).toHaveBeenCalledWith(7, 10)
    await waitFor(() => {
      expect(screen.getByText(/失敗理由: tts_request_failed/)).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: '試行1' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('過去の試行の取得に失敗した場合はエラーメッセージを表示する', async () => {
    const user = userEvent.setup()
    const data = baseData({
      timeline: [
        {
          source: 'phase', source_id: 20, generation_job_id: 1, operation: null,
          phase: 'synthesize', attempt_no: 2, result: 'success',
          occurred_at: '2026-08-14T10:05:00+00:00', started_at: '2026-08-14T10:05:00+00:00',
          ended_at: '2026-08-14T10:05:05+00:00', duration_ms: 5000, reason: null,
          tts_engine: 'voicevox', line_success_count: 1, line_total_count: 1,
        },
        {
          source: 'phase', source_id: 10, generation_job_id: 1, operation: null,
          phase: 'synthesize', attempt_no: 1, result: 'failure',
          occurred_at: '2026-08-14T10:00:00+00:00', started_at: '2026-08-14T10:00:00+00:00',
          ended_at: '2026-08-14T10:00:05+00:00', duration_ms: 5000, reason: null,
          tts_engine: 'voicevox', line_success_count: 0, line_total_count: 1,
        },
      ],
      lines: [{
        phase_log_id: 20, attempt_no: 2, script_line_index: 1, article_id: null,
        speaker: 'male', section: 'intro', delivery: 'neutral', tts_engine: 'voicevox',
        speaking_rate: 1.0, processing_duration_ms: 700, synth_result: 'success',
        retry_count: 0, wav_file: '001.wav', silence_before_sec: 0, start_time_sec: 1.2,
        failure_reason: null,
      }],
    })
    mockFetchClient.mockRejectedValueOnce(new Error('network error'))

    render(<AdminEpisodeLogsShell episodeId={7} initialData={data} />)
    await user.click(screen.getByRole('button', { name: '試行1' }))

    await waitFor(() => {
      expect(screen.getByText('過去の試行の取得に失敗しました。もう一度お試しください。')).toBeInTheDocument()
    })
  })
})

describe('AdminEpisodeLogsShell LLM呼び出し', () => {
  it('記録がない場合は専用メッセージを表示する', () => {
    render(<AdminEpisodeLogsShell episodeId={7} initialData={baseData()} />)
    expect(screen.getByText('LLM呼び出しの記録はありません。')).toBeInTheDocument()
  })

  it('JSONLダウンロードリンクがエピソードのダウンロードAPIを指す', () => {
    render(<AdminEpisodeLogsShell episodeId={7} initialData={baseData()} />)
    expect(screen.getByRole('link', { name: 'JSONLをダウンロード' })).toHaveAttribute(
      'href',
      '/api/admin/episodes/7/llm-calls/download',
    )
  })

  it('一覧は本文を含まずメタ情報のみ表示する', () => {
    const data = baseData({
      llm_calls: [{
        id: 1, call_id: 'call-1', episode_id: 7, phase: 'summarize', provider: 'ollama',
        model: 'qwen3', base_url: 'http://ollama.local', attempt: 1, status: 'success',
        latency_ms: 1200, created_at: '2026-08-14T10:00:00+00:00',
      }],
    })
    render(<AdminEpisodeLogsShell episodeId={7} initialData={data} />)
    expect(screen.getByText('要約（試行1）')).toBeInTheDocument()
    expect(screen.getByText('qwen3')).toBeInTheDocument()
    expect(mockFetchLlmCallClient).not.toHaveBeenCalled()
  })

  it('1件をクリックすると詳細APIを呼び出しprompt/response/thinkingを表示する', async () => {
    const user = userEvent.setup()
    const data = baseData({
      llm_calls: [{
        id: 1, call_id: 'call-1', episode_id: 7, phase: 'review', provider: 'ollama',
        model: 'qwen3', base_url: 'http://ollama.local', attempt: 2, status: 'success',
        latency_ms: 800, created_at: '2026-08-14T10:00:00+00:00',
      }],
    })
    mockFetchLlmCallClient.mockResolvedValueOnce({
      id: 1, call_id: 'call-1', episode_id: 7, phase: 'review', provider: 'ollama',
      model: 'qwen3', base_url: 'http://ollama.local', attempt: 2, status: 'success',
      latency_ms: 800, created_at: '2026-08-14T10:00:00+00:00',
      prompt_text: 'full prompt text', response_text: 'full response text', thinking_text: 'full thinking text',
    })

    render(<AdminEpisodeLogsShell episodeId={7} initialData={data} />)
    await user.click(screen.getByRole('button', { name: /レビュー/ }))

    expect(mockFetchLlmCallClient).toHaveBeenCalledWith(7, 'call-1')
    await waitFor(() => {
      expect(screen.getByText('full prompt text')).toBeInTheDocument()
    })
    expect(screen.getByText('full response text')).toBeInTheDocument()
    expect(screen.getByText('full thinking text')).toBeInTheDocument()
  })

  it('詳細取得に失敗した場合はエラーメッセージと再試行ボタンを表示する', async () => {
    const user = userEvent.setup()
    const data = baseData({
      llm_calls: [{
        id: 1, call_id: 'call-1', episode_id: 7, phase: 'script', provider: 'ollama',
        model: 'qwen3', base_url: 'http://ollama.local', attempt: 1, status: 'error',
        latency_ms: null, created_at: '2026-08-14T10:00:00+00:00',
      }],
    })
    mockFetchLlmCallClient.mockRejectedValueOnce(new Error('network error'))

    render(<AdminEpisodeLogsShell episodeId={7} initialData={data} />)
    await user.click(screen.getByRole('button', { name: /台本生成/ }))

    await waitFor(() => {
      expect(screen.getByText('本文の取得に失敗しました。')).toBeInTheDocument()
    })
  })
})
