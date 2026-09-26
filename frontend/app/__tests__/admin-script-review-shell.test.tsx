import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminScriptReviewShell from '../components/AdminScriptReviewShell'
import {
  clearDraftFromStorage,
  saveDraftToStorage,
  type AdminScriptReviewCastMember,
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

describe('AdminScriptReviewShell cast基準の話者選択', () => {
  const twoCast: AdminScriptReviewCastMember[] = [
    { key: 'mc-a', name: '田中' },
    { key: 'mc-b', name: '鈴木' },
  ]

  it('castが2人なら台本に1人しか登場しなくてもMC名で2人分選択できる', () => {
    const script = baseScript({ lines: [{ speaker: 'mc-a', section: 'intro', text: 'A' }] })
    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={script} initialCast={twoCast} />)

    const select = screen.getByLabelText('行1の話者') as HTMLSelectElement
    const optionLabels = Array.from(select.options).map((o) => o.textContent)
    expect(optionLabels).toEqual(['田中', '鈴木'])
  })

  it('castが1人なら台本に別keyの行があっても話者選択UIを表示しない', () => {
    const script = baseScript({
      lines: [
        { speaker: 'mc-a', section: 'intro', text: 'A' },
        { speaker: 'legacy-key', section: 'news', text: 'B' },
      ],
    })
    render(
      <AdminScriptReviewShell
        episodeId={1}
        initialRevision={1}
        initialScript={script}
        initialCast={[{ key: 'mc-a', name: '田中' }]}
      />,
    )
    expect(screen.queryByLabelText(/の話者/)).not.toBeInTheDocument()
  })

  it('castが1人でcast外のspeaker keyを持つ行は、選択UIを表示せず元のkeyを読み取り専用で表示する', () => {
    const script = baseScript({
      lines: [
        { speaker: 'mc-a', section: 'intro', text: 'A' },
        { speaker: 'legacy-key', section: 'news', text: 'B' },
      ],
    })
    render(
      <AdminScriptReviewShell
        episodeId={1}
        initialRevision={1}
        initialScript={script}
        initialCast={[{ key: 'mc-a', name: '田中' }]}
      />,
    )
    expect(screen.queryByLabelText(/の話者/)).not.toBeInTheDocument()
    // cast内のkeyと一致する行は通常の行番号表示のまま
    expect(screen.getByText('行1')).toBeInTheDocument()
    // cast外のkeyを持つ行は、別の出演者に見えないよう元のkeyが分かる表示にする
    expect(screen.getByText(/legacy-key/)).toBeInTheDocument()
  })

  it('cast外のspeaker keyを持つ行は現在値が元のkeyで分かり、勝手に書き換わらない', () => {
    const script = baseScript({
      lines: [
        { speaker: 'mc-a', section: 'intro', text: 'A' },
        { speaker: 'legacy-key', section: 'news', text: 'B' },
      ],
    })
    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={script} initialCast={twoCast} />)

    const secondSelect = screen.getByLabelText('行2の話者') as HTMLSelectElement
    expect(secondSelect.value).toBe('legacy-key')
    expect(Array.from(secondSelect.options).map((o) => o.textContent)).toEqual(['田中', '鈴木', 'legacy-key'])
  })

  it('castが無い過去回では既存動作（台本のspeaker keyから候補作成）に戻る', () => {
    const script = baseScript({
      lines: [
        { speaker: 'male', section: 'intro', text: 'A' },
        { speaker: 'female', section: 'news', text: 'B' },
      ],
    })
    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={script} initialCast={null} />)

    const select = screen.getByLabelText('行1の話者') as HTMLSelectElement
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['male', 'female'])
  })

  it('行追加時の初期話者はcastの先頭keyになる', async () => {
    const user = userEvent.setup()
    const script = baseScript({ lines: [{ speaker: 'mc-a', section: 'intro', text: 'A' }] })
    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={script} initialCast={twoCast} />)

    await user.click(screen.getByText('+ 行を追加'))
    const selects = screen.getAllByLabelText(/の話者/) as HTMLSelectElement[]
    expect(selects[selects.length - 1].value).toBe('mc-a')
  })

  it('cast外のspeaker keyを持つ行は、他のフィールドを編集して保存しても値が維持される', async () => {
    const user = userEvent.setup()
    const script = baseScript({
      lines: [
        { speaker: 'mc-a', section: 'intro', text: 'A' },
        { speaker: 'legacy-key', section: 'news', text: 'B' },
      ],
    })
    let submittedScript: AdminScriptReviewScript | null = null
    global.fetch = jest.fn().mockImplementation((_url: string, options?: RequestInit) => {
      if (options?.method === 'PUT') {
        submittedScript = (JSON.parse(options.body as string) as { script: AdminScriptReviewScript }).script
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ episode_id: 1, revision: 2, script: submittedScript }),
        })
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ episode_id: 1, revision: 2, script }) })
    }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={script} initialCast={twoCast} />)
    await user.type(screen.getAllByLabelText(/の本文/)[0], '追記')
    await user.click(screen.getByText('保存する'))

    await waitFor(() => expect(submittedScript).not.toBeNull())
    expect(submittedScript!.lines[1].speaker).toBe('legacy-key')
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

  it('保存中は行の編集操作を無効化し、送信後の入力で表示内容が失われない', async () => {
    const user = userEvent.setup()
    let resolvePut: () => void = () => {}
    const putResponse = new Promise<void>((resolve) => {
      resolvePut = resolve
    })
    let submittedScript: AdminScriptReviewScript | null = null
    global.fetch = jest.fn().mockImplementation((_url: string, options?: RequestInit) => {
      if (options?.method === 'PUT') {
        // 実APIは送信した台本をそのまま返すため、モックでもリクエスト本文をレスポンスに反映する
        submittedScript = (JSON.parse(options.body as string) as { script: AdminScriptReviewScript }).script
        return putResponse.then(() => ({
          ok: true,
          status: 200,
          json: async () => ({ episode_id: 1, revision: 2, script: submittedScript }),
        }))
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ episode_id: 1, revision: 2, script: baseScript() }) })
    }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    const firstTextarea = screen.getAllByLabelText(/の本文/)[0] as HTMLTextAreaElement
    await user.type(firstTextarea, '追記')
    await user.click(screen.getByText('保存する'))

    // 保存リクエストが完了するまでは、本文・行操作は無効化されている
    await waitFor(() => expect(firstTextarea).toBeDisabled())
    expect(screen.getByLabelText('行1を削除')).toBeDisabled()
    expect(screen.getByLabelText('行1を上へ')).toBeDisabled()
    expect(screen.getByText('+ 行を追加')).toBeDisabled()

    // 無効化中に本文が書き換わっても、画面表示（＝保存対象）は変化しない
    const valueBeforeBypass = firstTextarea.value
    fireEvent.change(firstTextarea, { target: { value: '保存中に紛れ込んだ入力' } })
    expect(firstTextarea.value).toBe(valueBeforeBypass)

    resolvePut()
    await waitFor(() => expect(firstTextarea).not.toBeDisabled())
    expect(screen.getByText(/版: 2/)).toBeInTheDocument()
    // 保存前に入力していた内容（追記）が応答後も画面に残っており、失われていないこと
    expect(screen.getByDisplayValue(/追記$/)).toBeInTheDocument()
    expect(screen.queryByDisplayValue(/保存中に紛れ込んだ入力/)).not.toBeInTheDocument()
  })
})

describe('AdminScriptReviewShell 試し聴き中の編集ブロックと遅延応答', () => {
  it('試し聴き中は行の編集操作を無効化する', async () => {
    const user = userEvent.setup()
    let resolvePreview: (value: unknown) => void = () => {}
    const previewResponse = new Promise((resolve) => {
      resolvePreview = resolve
    })
    global.fetch = jest.fn().mockImplementation(() => previewResponse) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.click(screen.getByLabelText('行1を試し聴き'))

    const firstTextarea = screen.getAllByLabelText(/の本文/)[0] as HTMLTextAreaElement
    await waitFor(() => expect(firstTextarea).toBeDisabled())
    expect(screen.getByLabelText('行1を削除')).toBeDisabled()
    expect(screen.getByText('+ 行を追加')).toBeDisabled()

    // 無効化中に本文が書き換わっても、表示中の台本は変化しない（古い音声を再生したように見せない）
    const valueBeforeBypass = firstTextarea.value
    fireEvent.change(firstTextarea, { target: { value: '試し聴き中に紛れ込んだ入力' } })
    expect(firstTextarea.value).toBe(valueBeforeBypass)

    resolvePreview({ ok: true, status: 200, blob: async () => new Blob(['audio']) })
    await waitFor(() => expect(firstTextarea).not.toBeDisabled())
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled()
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

  it('502エラー時は音声生成失敗メッセージを表示する', async () => {
    const user = userEvent.setup()
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 502 }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.click(screen.getByLabelText('行1を試し聴き'))

    await waitFor(() => expect(screen.getByText('音声の生成に失敗しました。もう一度お試しください。')).toBeInTheDocument())
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })
})

describe('AdminScriptReviewShell 行ごと・全体の指摘', () => {
  it('行に紐づく指摘は該当行を強調し、行番号なしの指摘は全体欄に表示する', async () => {
    const user = userEvent.setup()
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        can_approve: false,
        results: [
          { code: 'LINE', message: '1行目の指摘', line_indices: [0], severity: 'error' },
          { code: 'GLOBAL', message: '台本全体の指摘', line_indices: [], severity: 'warning' },
        ],
      }),
    }) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.click(screen.getByText('再チェック'))

    const firstLine = screen.getByLabelText('行1の本文').closest('div.rounded-2xl')
    const secondLine = screen.getByLabelText('行2の本文').closest('div.rounded-2xl')
    await waitFor(() => expect(screen.getByText('[エラー] 1行目の指摘')).toBeInTheDocument())
    expect(firstLine).toHaveClass('border-red-300', 'bg-red-50')
    expect(secondLine).toHaveClass('border-slate-200', 'bg-white')
    expect(screen.getByText('台本全体に関する指摘').parentElement).toHaveTextContent('[警告] 台本全体の指摘')
  })
})

describe('AdminScriptReviewShell 再チェック中の編集と古い検査結果', () => {
  it('検査中に編集すると、後から届いた検査結果は反映しない', async () => {
    const user = userEvent.setup()
    let resolveValidate: (value: unknown) => void = () => {}
    const validateResponse = new Promise((resolve) => {
      resolveValidate = resolve
    })
    global.fetch = jest.fn().mockImplementation(() => validateResponse) as unknown as typeof fetch

    render(<AdminScriptReviewShell episodeId={1} initialRevision={1} initialScript={baseScript()} />)
    await user.click(screen.getByText('再チェック'))
    expect(screen.getByText('検査中...')).toBeInTheDocument()

    // 検査の応答を待つ間に編集すると未保存状態になる（再チェックはこの時点では止めない）
    await user.type(screen.getAllByLabelText(/の本文/)[0], '追記')
    expect(screen.getByText('未保存の変更があります')).toBeInTheDocument()

    resolveValidate({
      ok: true,
      status: 200,
      json: async () => ({
        can_approve: false,
        results: [{ code: 'X', message: '編集前の内容に対する指摘', line_indices: [0], severity: 'error' }],
      }),
    })

    await waitFor(() => expect(screen.queryByText('検査中...')).not.toBeInTheDocument())
    // 編集後に届いた古い検査結果は表示しない
    expect(screen.queryByText('編集前の内容に対する指摘')).not.toBeInTheDocument()
    expect(screen.queryByText('検査エラーが残っています。承認する前に修正してください。')).not.toBeInTheDocument()
  })
})
