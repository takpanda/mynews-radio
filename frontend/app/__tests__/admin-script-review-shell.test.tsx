import '@testing-library/jest-dom'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminScriptReviewShell from '../components/AdminScriptReviewShell'
import {
  clearDraftFromStorage,
  saveDraftToStorage,
  type AdminScriptReviewScript,
} from '../lib/admin-script-review'

jest.mock('react-hot-toast', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}))

function baseScript(overrides: Partial<AdminScriptReviewScript> = {}): AdminScriptReviewScript {
  return {
    lines: [
      { speaker: 'male', section: 'intro', text: 'おはようございます' },
      { speaker: 'male', section: 'news', text: '本日のニュースです' },
    ],
    ...overrides,
  }
}

beforeEach(() => {
  window.localStorage.clear()
  HTMLMediaElement.prototype.play = jest.fn().mockResolvedValue(undefined)
  HTMLMediaElement.prototype.pause = jest.fn()
  global.URL.createObjectURL = jest.fn(() => 'blob:mock-url')
  global.URL.revokeObjectURL = jest.fn()
})

afterEach(() => {
  jest.restoreAllMocks()
  clearDraftFromStorage(1)
})

describe('AdminScriptReviewShell 基本表示', () => {
  it('台本の行と版番号を表示する', () => {
    render(<AdminScriptReviewShell episodeId={1} initialRevision={3} initialScript={baseScript()} />)
    expect(screen.getByText(/版: 3/)).toBeInTheDocument()
    expect(screen.getByDisplayValue('おはようございます')).toBeInTheDocument()
    expect(screen.getByDisplayValue('本日のニュースです')).toBeInTheDocument()
  })

  it('speakerが1種類の場合は話者選択を表示しない', () => {
    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    expect(screen.queryByLabelText(/の話者/)).not.toBeInTheDocument()
  })

  it('speakerが複数種類の場合は話者選択を表示する', () => {
    const script = baseScript({
      lines: [
        { speaker: 'male', section: 'intro', text: 'A' },
        { speaker: 'female', section: 'news', text: 'B' },
      ],
    })
    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={script} />)
    expect(screen.getAllByLabelText(/の話者/).length).toBe(2)
  })
})

describe('AdminScriptReviewShell 行編集', () => {
  it('行を追加・削除・並べ替えできる', async () => {
    const user = userEvent.setup()
    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)

    await user.click(screen.getByText('+ 行を追加'))
    const textareas = screen.getAllByLabelText(/の本文/)
    expect(textareas).toHaveLength(3)

    await user.click(screen.getByLabelText('行3を削除'))
    expect(screen.getAllByLabelText(/の本文/)).toHaveLength(2)

    const firstTextBefore = (screen.getAllByLabelText(/の本文/)[0] as HTMLTextAreaElement).value
    await user.click(screen.getByLabelText('行2を上へ'))
    const firstTextAfter = (screen.getAllByLabelText(/の本文/)[0] as HTMLTextAreaElement).value
    expect(firstTextAfter).not.toBe(firstTextBefore)
  })

  it('編集すると未保存の変更ありと表示し、再チェック・試し聴きを無効化する', async () => {
    const user = userEvent.setup()
    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)

    await user.type(screen.getAllByLabelText(/の本文/)[0], '追記')
    expect(screen.getByText('未保存の変更があります')).toBeInTheDocument()
    expect(screen.getByText('再チェック')).toBeDisabled()
    expect(screen.getByLabelText('行1を試し聴き')).toBeDisabled()
    expect(screen.getByText('承認する')).toBeDisabled()
  })
})

describe('AdminScriptReviewShell 保存', () => {
  it('保存成功で版が更新され未保存表示が消える', async () => {
    const user = userEvent.setup()
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ episode_id: 1, revision: 2, script: baseScript() }),
    }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.type(screen.getAllByLabelText(/の本文/)[0], '追記')
    await user.click(screen.getByText('保存する'))

    await waitFor(() => expect(screen.getByText(/版: 2/)).toBeInTheDocument())
    expect(screen.queryByText('未保存の変更があります')).not.toBeInTheDocument()
  })

  it('409競合時は差分を表示し、自動上書きしない', async () => {
    const user = userEvent.setup()
    const serverScript = baseScript({
      lines: [
        { speaker: 'male', section: 'intro', text: 'おはようございます' },
        { speaker: 'male', section: 'news', text: '別の人が変更した内容' },
      ],
    })
    global.fetch = jest.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (options?.method === 'PUT') {
        return Promise.resolve({
          ok: false,
          status: 409,
          json: async () => ({ detail: { message: 'Script revision conflict', latest_revision: 5 } }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ episode_id: 1, revision: 5, script: serverScript }),
      })
    }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.type(screen.getAllByLabelText(/の本文/)[0], '追記')
    await user.click(screen.getByText('保存する'))

    await waitFor(() => expect(screen.getByText(/現在の版: 5/)).toBeInTheDocument())
    expect(screen.getByText('サーバーの最新版を使う（編集を破棄）')).toBeInTheDocument()
    // 自動上書きしていないこと（ヘッダーの版表示はまだ1のまま、編集内容も残っている）
    expect(screen.getByText(/エピソードID: 1 ・ 版: 1/)).toBeInTheDocument()
    expect(screen.getByDisplayValue(/追記$/)).toBeInTheDocument()
  })

  it('競合後にサーバー版を採用すると編集が破棄される', async () => {
    const user = userEvent.setup()
    const serverScript = baseScript({
      lines: [{ speaker: 'male', section: 'intro', text: 'サーバー版の内容' }],
    })
    global.fetch = jest.fn().mockImplementation((_url: string, options?: RequestInit) => {
      if (options?.method === 'PUT') {
        return Promise.resolve({
          ok: false,
          status: 409,
          json: async () => ({ detail: { message: 'Script revision conflict', latest_revision: 5 } }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ episode_id: 1, revision: 5, script: serverScript }),
      })
    }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.type(screen.getAllByLabelText(/の本文/)[0], '追記')
    await user.click(screen.getByText('保存する'))
    await waitFor(() => expect(screen.getByText('サーバーの最新版を使う（編集を破棄）')).toBeInTheDocument())

    await user.click(screen.getByText('サーバーの最新版を使う（編集を破棄）'))
    expect(screen.getByDisplayValue('サーバー版の内容')).toBeInTheDocument()
    expect(screen.getByText(/版: 5/)).toBeInTheDocument()
  })
})

describe('AdminScriptReviewShell 下書き復元', () => {
  it('同じ版の下書きがあれば復元できる', async () => {
    const user = userEvent.setup()
    saveDraftToStorage(1, 1, baseScript({ lines: [{ speaker: 'male', section: 'intro', text: '端末に残っていた下書き' }] }))

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    expect(screen.getByText('端末に保存された下書きがあります。')).toBeInTheDocument()

    await user.click(screen.getByText('下書きを復元する'))
    expect(screen.getByDisplayValue('端末に残っていた下書き')).toBeInTheDocument()
  })

  it('サーバー版が進んでいる場合は差分と選択肢を表示する', () => {
    saveDraftToStorage(1, 1, baseScript({ lines: [{ speaker: 'male', section: 'intro', text: '古い下書き' }] }))

    render(<AdminScriptReviewShell episodeId={1} initialRevision={3} initialScript={baseScript()} />)
    expect(screen.getByText(/下書きの元版: 1 \/ 現在の版: 3/)).toBeInTheDocument()
    expect(screen.getByText('下書きの内容を反映する')).toBeInTheDocument()
    expect(screen.getByText('サーバー最新版を使う（下書きを破棄）')).toBeInTheDocument()
  })
})

describe('AdminScriptReviewShell 承認・破棄', () => {
  it('承認確認ダイアログを経て承認し、検査エラーが残っていれば表示する', async () => {
    const user = userEvent.setup()
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        detail: {
          message: 'Script has validation errors',
          results: [{ code: 'X', message: 'まだNGです', line_indices: [], severity: 'error' }],
        },
      }),
    }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.click(screen.getByText('承認する'))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText('承認する'))

    await waitFor(() => expect(screen.getByText('まだNGです')).toBeInTheDocument())
  })

  it('破棄確認ダイアログを経て破棄すると終了メッセージを表示する', async () => {
    const user = userEvent.setup()
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ episode_id: 1, status: 'discarded' }),
    }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.click(screen.getByText('破棄する'))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByText('破棄する'))

    await waitFor(() => expect(screen.getByText('この台本は破棄されました。')).toBeInTheDocument())
  })
})

describe('AdminScriptReviewShell 試し聴き', () => {
  it('429エラー時は利用回数上限メッセージを表示する', async () => {
    const user = userEvent.setup()
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 429 }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.click(screen.getByLabelText('行1を試し聴き'))

    await waitFor(() => expect(screen.getByText(/上限に達しました/)).toBeInTheDocument())
  })
})
