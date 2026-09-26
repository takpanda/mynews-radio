import '@testing-library/jest-dom'

import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminDryRunShell from '../components/AdminDryRunShell'
import type { ProgramDefinitionValue } from '../lib/admin-programs'

const replaceMock = jest.fn()

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => '/admin/programs/p1/dry-run',
}))

function jsonResponse(status: number, body: unknown, headers?: Record<string, string>) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
    headers: { get: (name: string) => headers?.[name] ?? null },
  }
}

function baseDefinition(): ProgramDefinitionValue {
  return {
    id: 'p1',
    name: 'テスト番組',
    kind: 'radio',
    cast: [{ key: 'male', name: '田村', role: 'メインMC', mc_id: null, voice_fishs2pro: null, voice_aivispeech: null, voice_voicevox: null }],
    segments: [],
    options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
  }
}

beforeEach(() => {
  global.fetch = jest.fn()
  replaceMock.mockClear()
})

afterEach(() => {
  jest.useRealTimers()
})

describe('AdminDryRunShell', () => {
  it('radio以外の番組では実行ボタンが無効で未対応メッセージを表示し、POSTされない', async () => {
    const user = userEvent.setup()
    render(
      <AdminDryRunShell programId="p1" programKind="commentary" currentDefinition={baseDefinition()} initialDryRunId={null} />,
    )

    expect(screen.getByText('この番組タイプはテスト生成未対応')).toBeInTheDocument()
    const button = screen.getByRole('button', { name: 'テスト生成を実行' })
    expect(button).toBeDisabled()
    await user.click(button)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('下書き番組定義に不正なJSONを入力すると送信せずエラーを表示する', async () => {
    const user = userEvent.setup()
    render(<AdminDryRunShell programId="p1" programKind="radio" currentDefinition={baseDefinition()} initialDryRunId={null} />)

    await user.type(screen.getByLabelText('下書き番組定義（JSON）'), 'not valid json')
    await user.click(screen.getByRole('button', { name: 'テスト生成を実行' }))

    expect(await screen.findByText('下書き番組定義はJSON形式で入力してください。')).toBeInTheDocument()
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('過去回IDに0以下の値を入力すると送信せずエラーを表示する', async () => {
    const user = userEvent.setup()
    render(<AdminDryRunShell programId="p1" programKind="radio" currentDefinition={baseDefinition()} initialDryRunId={null} />)

    await user.type(screen.getByLabelText('過去回ID'), '0')
    await user.click(screen.getByRole('button', { name: 'テスト生成を実行' }))

    expect(await screen.findByText('過去回IDは1以上の整数で入力してください。')).toBeInTheDocument()
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('入力不備の422応答をそのままエラーメッセージとして表示する', async () => {
    const user = userEvent.setup()
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(422, { detail: '指定エピソードの summaries.json が読み取れません' }),
    )
    render(<AdminDryRunShell programId="p1" programKind="radio" currentDefinition={baseDefinition()} initialDryRunId={null} />)

    await user.type(screen.getByLabelText('過去回ID'), '99999')
    await user.click(screen.getByRole('button', { name: 'テスト生成を実行' }))

    expect(await screen.findByText('指定エピソードの summaries.json が読み取れません')).toBeInTheDocument()
  })

  it('待機上限（429）はRetry-Afterの秒数を含むメッセージを表示する', async () => {
    const user = userEvent.setup()
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(429, { detail: 'Generation queue is full' }, { 'Retry-After': '60' }),
    )
    render(<AdminDryRunShell programId="p1" programKind="radio" currentDefinition={baseDefinition()} initialDryRunId={null} />)

    await user.click(screen.getByRole('button', { name: 'テスト生成を実行' }))

    expect(await screen.findByText('生成キューが上限に達しています。しばらく待ってから再実行してください。')).toBeInTheDocument()
    expect(screen.getByText('60秒ほど待ってから再実行してください。')).toBeInTheDocument()
  })

  it('受付後は待機中→生成中→完了と状態が進み、現在版・下書き版の台本とチェック結果を比較表示する', async () => {
    jest.useFakeTimers()
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })

    const detailBase = {
      id: 1,
      program_id: 'p1',
      program_definition: {},
      draft_program_definition: {},
      prompt_version_id: null,
      input_episode_id: null,
      error: null,
      created_at: '',
      updated_at: '',
    }

    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(jsonResponse(202, { id: 1, status: 'queued' }))
      .mockResolvedValueOnce(jsonResponse(200, { ...detailBase, status: 'queued', script_json: null, validation_json: null }))
      .mockResolvedValueOnce(jsonResponse(200, { ...detailBase, status: 'running', script_json: null, validation_json: null }))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          ...detailBase,
          status: 'completed',
          script_json: {
            current: { lines: [{ speaker: 'male', text: '現在版の本文', section: 'news' }] },
            draft: { lines: [{ speaker: 'male', text: '下書き版の本文', section: 'news' }] },
          },
          validation_json: {
            current: [{ code: 'X', message: '現在版の警告', line_indices: [0], severity: 'warning' }],
            draft: [{ code: 'Y', message: '下書き版のエラー', line_indices: [0], severity: 'error' }],
          },
        }),
      )

    render(<AdminDryRunShell programId="p1" programKind="radio" currentDefinition={baseDefinition()} initialDryRunId={null} />)

    await user.click(screen.getByRole('button', { name: 'テスト生成を実行' }))

    await waitFor(() => expect(screen.getByText('待機中')).toBeInTheDocument())
    expect(replaceMock).toHaveBeenCalledWith('/admin/programs/p1/dry-run?dry_run_id=1', { scroll: false })

    await act(async () => {
      await jest.advanceTimersByTimeAsync(3000)
    })
    await waitFor(() => expect(screen.getByText('生成中')).toBeInTheDocument())

    await act(async () => {
      await jest.advanceTimersByTimeAsync(3000)
    })
    await waitFor(() => expect(screen.getByText('完了')).toBeInTheDocument())

    expect(screen.getByText('現在版の本文')).toBeInTheDocument()
    expect(screen.getByText('下書き版の本文')).toBeInTheDocument()
    expect(screen.getByText('[警告] 現在版の警告')).toBeInTheDocument()
    expect(screen.getByText('[エラー] 下書き版のエラー')).toBeInTheDocument()

    // 完了後はポーリングを止め、追加のGETは発行しない
    const callCountAfterCompletion = (global.fetch as jest.Mock).mock.calls.length
    await act(async () => {
      await jest.advanceTimersByTimeAsync(6000)
    })
    expect((global.fetch as jest.Mock).mock.calls.length).toBe(callCountAfterCompletion)
  })

  it('失敗状態ではエラー内容を表示する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(jsonResponse(202, { id: 2, status: 'running' }))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          id: 2,
          program_id: 'p1',
          program_definition: {},
          draft_program_definition: null,
          prompt_version_id: null,
          input_episode_id: null,
          script_json: null,
          validation_json: null,
          status: 'failed',
          error: '台本生成に使える記事要約がありません',
          created_at: '',
          updated_at: '',
        }),
      )
    const user = userEvent.setup()
    render(<AdminDryRunShell programId="p1" programKind="radio" currentDefinition={baseDefinition()} initialDryRunId={null} />)

    await user.click(screen.getByRole('button', { name: 'テスト生成を実行' }))

    expect(await screen.findByText('失敗')).toBeInTheDocument()
    expect(screen.getByText('台本生成に使える記事要約がありません')).toBeInTheDocument()
  })

  it('URLにdry_run_idがある場合は再読込後もジョブIDから結果を開ける', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(200, {
        id: 7,
        program_id: 'p1',
        program_definition: {},
        draft_program_definition: null,
        prompt_version_id: null,
        input_episode_id: null,
        script_json: { current: { lines: [{ speaker: 'male', text: '復元された本文', section: 'news' }] } },
        validation_json: { current: [] },
        status: 'completed',
        error: null,
        created_at: '',
        updated_at: '',
      }),
    )

    render(<AdminDryRunShell programId="p1" programKind="radio" currentDefinition={baseDefinition()} initialDryRunId={7} />)

    expect(await screen.findByText('復元された本文')).toBeInTheDocument()
    expect(screen.getByText('実行結果（ジョブID: 7）')).toBeInTheDocument()
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/dry-runs/7', expect.anything())
  })
})
