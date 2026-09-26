import '@testing-library/jest-dom'

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminProgramFormShell from '../components/AdminProgramFormShell'
import type { ProgramDefinitionValue } from '../lib/admin-programs'
import type { VoiceOptionsResponse } from '../lib/admin-voice-settings'

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}))

const VOICE_OPTIONS_URL = '/api/admin/settings/voices/options'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

const DEFAULT_VOICE_OPTIONS: VoiceOptionsResponse = {
  aivispeech: { status: 'ok', options: [], error: null },
  voicevox: { status: 'ok', options: [], error: null },
  fishs2pro: {
    status: 'ok',
    options: [
      { display_name: 'ナレーターA', value: 'voice_a', speaker_name: null, style_name: null },
      { display_name: 'ナレーターB', value: 'voice_b', speaker_name: null, style_name: null },
    ],
    error: null,
  },
}

function baseProgram(segmentCount = 0): ProgramDefinitionValue {
  return {
    id: 'p1',
    name: 'テスト番組',
    kind: 'radio',
    cast: [{ key: 'male', name: '田村', role: 'メインMC', mc_id: null, voice_fishs2pro: null, voice_aivispeech: null, voice_voicevox: null }],
    segments: Array.from({ length: segmentCount }, (_, i) => ({
      id: `seg${i}`,
      kind: 'news',
      order: i,
      min_lines: 1,
      max_lines: 2,
      speaker_keys: ['male'],
      label: '',
    })),
    options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
  }
}

/**
 * global.fetch のルーティングモック。ボイス一覧（GET /api/admin/settings/voices/options）はマウント時に
 * 必ず呼ばれるため voiceOptionsResponse を返し、それ以外（番組の作成・更新API）は programResponse を返す。
 */
function setupFetch(
  programResponse: (url: string, options?: RequestInit) => unknown,
  voiceOptionsResponse: unknown = jsonResponse(200, DEFAULT_VOICE_OPTIONS),
) {
  ;(global.fetch as jest.Mock).mockImplementation((url: string, options?: RequestInit) => {
    if (url === VOICE_OPTIONS_URL) return Promise.resolve(voiceOptionsResponse)
    try {
      return Promise.resolve(programResponse(url, options))
    } catch (err) {
      return Promise.reject(err)
    }
  })
}

function programFetchCalls() {
  return (global.fetch as jest.Mock).mock.calls.filter(([url]) => url !== VOICE_OPTIONS_URL)
}

/** 各テストの操作前に、マウント時のボイス一覧取得（Fish S2 Proプルダウンの読み込み）を完了させる */
async function renderShell(props: Parameters<typeof AdminProgramFormShell>[0]) {
  const utils = render(<AdminProgramFormShell {...props} />)
  await waitFor(() => expect(screen.getAllByLabelText(/^Fish S2 Pro/)[0]).not.toBeDisabled())
  return utils
}

beforeEach(() => {
  global.fetch = jest.fn()
  setupFetch(() => {
    throw new Error('この操作では番組APIは呼ばれない想定です')
  })
})

describe('AdminProgramFormShell', () => {
  it('セグメントが6件のとき追加するとエラーを表示し、7件目は追加されない', async () => {
    const user = userEvent.setup()
    await renderShell({ mode: 'edit', initialProgram: baseProgram(6), initialIsActive: true, mcs: [] })

    expect(screen.getByText('セグメント（6/6）')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'セグメントを追加' }))

    expect(screen.getByText('セグメントは最大6件までです')).toBeInTheDocument()
    expect(screen.getByText('セグメント（6/6）')).toBeInTheDocument()
    expect(programFetchCalls()).toHaveLength(0)
  })

  it('編集の保存は確認ダイアログを開き、変更メモが空だと送信しない', async () => {
    const user = userEvent.setup()
    await renderShell({ mode: 'edit', initialProgram: baseProgram(1), initialIsActive: true, mcs: [] })

    await user.click(screen.getByRole('button', { name: '保存する' }))
    const dialog = await screen.findByRole('dialog')

    await user.click(within(dialog).getByRole('button', { name: '保存する' }))
    expect(await within(dialog).findByText('変更メモを入力してください')).toBeInTheDocument()
    expect(programFetchCalls()).toHaveLength(0)
  })

  it('編集の保存はキャンセルするとPUTが送信されない', async () => {
    const user = userEvent.setup()
    await renderShell({ mode: 'edit', initialProgram: baseProgram(1), initialIsActive: true, mcs: [] })

    await user.click(screen.getByRole('button', { name: '保存する' }))
    const dialog = await screen.findByRole('dialog')

    await user.type(within(dialog).getByLabelText('変更メモ'), 'テストのため変更')
    await user.click(within(dialog).getByRole('button', { name: 'キャンセル' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(programFetchCalls()).toHaveLength(0)
  })

  it('変更メモを入力して確定すると、cast/segments/optionsを含むPUTが送信される', async () => {
    const responseDefinition = { ...baseProgram(1), name: '更新後の番組名' }
    setupFetch(() =>
      jsonResponse(200, {
        id: 'p1',
        name: '更新後の番組名',
        kind: 'radio',
        definition: responseDefinition,
        is_active: true,
        created_at: '',
        updated_at: '',
      }),
    )
    const user = userEvent.setup()
    await renderShell({ mode: 'edit', initialProgram: baseProgram(1), initialIsActive: true, mcs: [] })

    await user.click(screen.getByRole('button', { name: '保存する' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('変更メモ'), 'テストのため変更')
    await user.click(within(dialog).getByRole('button', { name: '保存する' }))

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/admin/programs/p1', expect.objectContaining({ method: 'PUT' })))
    const [, options] = programFetchCalls()[0]
    const sentBody = JSON.parse(options.body as string)
    expect(sentBody).toMatchObject({
      id: 'p1',
      name: 'テスト番組',
      kind: 'radio',
      is_active: true,
      cast: [{ key: 'male', name: '田村', role: 'メインMC' }],
      segments: [{ id: 'seg0', kind: 'news', order: 0, min_lines: 1, max_lines: 2, speaker_keys: ['male'] }],
      options: { review_mode: 'on_failure', narrative_arc: false },
    })
    // 変更メモ本文はAPIへ送らない（バックエンドは受け取らないため）
    expect(sentBody.change_note).toBeUndefined()

    // 保存後はPUT応答の値が画面に反映される
    expect(await screen.findByDisplayValue('更新後の番組名')).toBeInTheDocument()
  })

  it('編集の保存で422応答があると、確認ダイアログ内にエラーが表示され再送信できる', async () => {
    setupFetch(() => ({
      ok: false,
      status: 422,
      text: () => Promise.resolve(JSON.stringify({ detail: 'Unknown or inactive MC: radio_male' })),
    }))
    const user = userEvent.setup()
    await renderShell({ mode: 'edit', initialProgram: baseProgram(1), initialIsActive: true, mcs: [] })

    await user.click(screen.getByRole('button', { name: '保存する' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('変更メモ'), 'テストのため変更')
    await user.click(within(dialog).getByRole('button', { name: '保存する' }))

    expect(await within(dialog).findByText('Unknown or inactive MC: radio_male')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('種別をradioからcommentaryへ変更すると、narrative_arcは自動でオフになるが、非対応セグメント種類は自動変換せず保存をブロックする', async () => {
    const user = userEvent.setup()
    const program = baseProgram(1)
    program.options.narrative_arc = true
    program.segments[0].kind = 'transition'
    await renderShell({ mode: 'edit', initialProgram: program, initialIsActive: true, mcs: [] })

    expect(screen.getByRole('checkbox', { name: '物語構成（narrative_arc）を使う' })).toBeChecked()

    await user.selectOptions(screen.getByDisplayValue('ラジオ'), 'commentary')

    // commentary用のオプションUIに切り替わり、narrative_arcチェックボックスは表示されない
    expect(screen.queryByRole('checkbox', { name: '物語構成（narrative_arc）を使う' })).not.toBeInTheDocument()

    // セグメント種類は自動変換されず、元の値（つなぎ=transition）のまま「使用できません」と明示される
    expect(screen.getByText((_, el) => el?.tagName === 'OPTION' && el.textContent === 'つなぎ（現在の種別では使用できません）')).toBeInTheDocument()
    expect(screen.getByText('種類を選び直してください')).toBeInTheDocument()

    // 直さずに保存しようとすると、種類の選び直しを促すエラーで保存はブロックされる（確認ダイアログは開かない）
    await user.click(screen.getByRole('button', { name: '保存する' }))
    expect(await screen.findByText(/は種別「解説」では使用できません/)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(programFetchCalls()).toHaveLength(0)

    // セグメントの種類を管理者自身が有効な値へ選び直すと保存できる
    await user.selectOptions(screen.getByDisplayValue('つなぎ（現在の種別では使用できません）'), 'news')

    setupFetch(() =>
      jsonResponse(200, {
        id: program.id,
        name: program.name,
        kind: 'commentary',
        definition: { ...program, kind: 'commentary', segments: [{ ...program.segments[0], kind: 'news' }], options: { ...program.options, narrative_arc: false } },
        is_active: true,
        created_at: '',
        updated_at: '',
      }),
    )

    await user.click(screen.getByRole('button', { name: '保存する' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('変更メモ'), 'kind変更のテスト')
    await user.click(within(dialog).getByRole('button', { name: '保存する' }))

    await waitFor(() => expect(programFetchCalls()).toHaveLength(1))
    const [, fetchOptions] = programFetchCalls()[0]
    const sentBody = JSON.parse(fetchOptions.body as string)
    expect(sentBody.kind).toBe('commentary')
    expect(sentBody.options.narrative_arc).toBe(false)
    expect(sentBody.segments[0].kind).toBe('news')
  })

  it('新規作成は確認ダイアログなしで、cast/segments/optionsを含むPOSTを送信する', async () => {
    setupFetch(() =>
      jsonResponse(201, {
        id: 'p2',
        name: '新番組',
        kind: 'radio',
        definition: { ...baseProgram(0), id: 'p2', name: '新番組' },
        is_active: true,
        created_at: '',
        updated_at: '',
      }),
    )
    const user = userEvent.setup()
    const created = baseProgram(0)
    created.id = 'p2'
    created.name = '新番組'
    await renderShell({ mode: 'create', initialProgram: created, initialIsActive: true, mcs: [] })

    await user.click(screen.getByRole('button', { name: '作成する' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/admin/programs', expect.objectContaining({ method: 'POST' })))

    const [, fetchOptions] = programFetchCalls()[0]
    const sentBody = JSON.parse(fetchOptions.body as string)
    expect(sentBody).toMatchObject({
      id: 'p2',
      name: '新番組',
      kind: 'radio',
      is_active: true,
      cast: [{ key: 'male', name: '田村', role: 'メインMC' }],
      segments: [],
      options: { review_mode: 'on_failure', narrative_arc: false, style: null, mc_gender: null },
    })
  })

  it('編集フォームはPCのみ、閲覧サマリーはスマホのみ表示するクラス構成になっている', async () => {
    // jsdomはメディアクエリを評価しないため、実際の375px/PC幅の見え方はPlaywright等の実ブラウザ確認が必要。
    // ここでは責務分割用のコンテナ（hidden md:block / md:hidden）が外れていないことを回帰的に検知する。
    const { getByTestId } = await renderShell({ mode: 'edit', initialProgram: baseProgram(1), initialIsActive: true, mcs: [] })
    const editForm = getByTestId('program-edit-form')
    expect(editForm).toHaveClass('hidden')
    expect(editForm).toHaveClass('md:block')
    expect(within(editForm).getByRole('button', { name: '保存する' })).toBeInTheDocument()

    const mobileSummary = getByTestId('program-mobile-summary')
    expect(mobileSummary).toHaveClass('md:hidden')
    expect(within(mobileSummary).queryByRole('button', { name: '保存する' })).not.toBeInTheDocument()
  })

  describe('キャスト行のFish S2 Proプルダウン', () => {
    it('一覧取得中は読み込み中の無効化されたプルダウンを表示し、取得後はブランクと選択肢が並ぶ', async () => {
      render(<AdminProgramFormShell mode="edit" initialProgram={baseProgram(1)} initialIsActive={true} mcs={[]} />)

      const select = screen.getByLabelText('Fish S2 Pro（1人目）') as HTMLSelectElement
      expect(select).toBeDisabled()
      expect(within(select).getByText('読み込み中…')).toBeInTheDocument()

      await waitFor(() => expect(select).not.toBeDisabled())
      const options = within(select).getAllByRole('option') as HTMLOptionElement[]
      expect(options.map((o) => o.textContent)).toEqual(['ブランク（未指定）', 'ナレーターA', 'ナレーターB'])
      expect(select.value).toBe('')
    })

    it('ボイスを選んで保存すると、そのvalueがvoice_fishs2proとして送信される', async () => {
      setupFetch(() =>
        jsonResponse(200, {
          id: 'p1',
          name: 'テスト番組',
          kind: 'radio',
          definition: baseProgram(1),
          is_active: true,
          created_at: '',
          updated_at: '',
        }),
      )
      const user = userEvent.setup()
      await renderShell({ mode: 'edit', initialProgram: baseProgram(1), initialIsActive: true, mcs: [] })

      const select = await screen.findByLabelText('Fish S2 Pro（1人目）')
      await waitFor(() => expect(select).not.toBeDisabled())
      await user.selectOptions(select, 'voice_b')

      await user.click(screen.getByRole('button', { name: '保存する' }))
      const dialog = await screen.findByRole('dialog')
      await user.type(within(dialog).getByLabelText('変更メモ'), 'ボイス選択のテスト')
      await user.click(within(dialog).getByRole('button', { name: '保存する' }))

      await waitFor(() => expect(programFetchCalls()).toHaveLength(1))
      const [, fetchOptions] = programFetchCalls()[0]
      const sentBody = JSON.parse(fetchOptions.body as string)
      expect(sentBody.cast[0].voice_fishs2pro).toBe('voice_b')
    })

    it('保存済みの値からブランク（未指定）を選んで保存すると、voice_fishs2pro: nullが送信される', async () => {
      const program = baseProgram(1)
      program.cast[0].voice_fishs2pro = 'voice_a'
      setupFetch(() =>
        jsonResponse(200, {
          id: 'p1',
          name: 'テスト番組',
          kind: 'radio',
          definition: program,
          is_active: true,
          created_at: '',
          updated_at: '',
        }),
      )
      const user = userEvent.setup()
      await renderShell({ mode: 'edit', initialProgram: program, initialIsActive: true, mcs: [] })

      const select = await screen.findByLabelText('Fish S2 Pro（1人目）')
      await waitFor(() => expect(select).not.toBeDisabled())
      expect((select as HTMLSelectElement).value).toBe('voice_a')

      await user.selectOptions(select, '')

      await user.click(screen.getByRole('button', { name: '保存する' }))
      const dialog = await screen.findByRole('dialog')
      await user.type(within(dialog).getByLabelText('変更メモ'), 'ブランクへ変更'.trim())
      await user.click(within(dialog).getByRole('button', { name: '保存する' }))

      await waitFor(() => expect(programFetchCalls()).toHaveLength(1))
      const [, fetchOptions] = programFetchCalls()[0]
      const sentBody = JSON.parse(fetchOptions.body as string)
      expect(sentBody.cast[0].voice_fishs2pro).toBeNull()
    })

    it('保存済みの値が一覧に無い場合、その値が選択中として表示され、無操作で保存しても値が変わらない', async () => {
      const program = baseProgram(1)
      program.cast[0].voice_fishs2pro = 'old_voice'
      setupFetch(() =>
        jsonResponse(200, {
          id: 'p1',
          name: 'テスト番組',
          kind: 'radio',
          definition: program,
          is_active: true,
          created_at: '',
          updated_at: '',
        }),
      )
      const user = userEvent.setup()
      await renderShell({ mode: 'edit', initialProgram: program, initialIsActive: true, mcs: [] })

      const select = (await screen.findByLabelText('Fish S2 Pro（1人目）')) as HTMLSelectElement
      await waitFor(() => expect(select).not.toBeDisabled())
      expect(select.value).toBe('old_voice')
      expect(within(select).getByText('old_voice（一覧にありません）')).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: '保存する' }))
      const dialog = await screen.findByRole('dialog')
      await user.type(within(dialog).getByLabelText('変更メモ'), '無操作で保存')
      await user.click(within(dialog).getByRole('button', { name: '保存する' }))

      await waitFor(() => expect(programFetchCalls()).toHaveLength(1))
      const [, fetchOptions] = programFetchCalls()[0]
      const sentBody = JSON.parse(fetchOptions.body as string)
      expect(sentBody.cast[0].voice_fishs2pro).toBe('old_voice')
    })

    it('一覧のstatusがerrorの場合、エラーメッセージを表示しつつブランクと保存済みの値は選択でき、保存も妨げない', async () => {
      const program = baseProgram(1)
      program.cast[0].voice_fishs2pro = 'old_voice'
      const errorVoiceOptions: VoiceOptionsResponse = {
        ...DEFAULT_VOICE_OPTIONS,
        fishs2pro: { status: 'error', options: [], error: 'Fish S2 Proサーバーに接続できませんでした' },
      }
      setupFetch(
        () =>
          jsonResponse(200, {
            id: 'p1',
            name: 'テスト番組',
            kind: 'radio',
            definition: program,
            is_active: true,
            created_at: '',
            updated_at: '',
          }),
        jsonResponse(200, errorVoiceOptions),
      )
      const user = userEvent.setup()
      await renderShell({ mode: 'edit', initialProgram: program, initialIsActive: true, mcs: [] })

      expect(await screen.findByText('Fish S2 Proサーバーに接続できませんでした')).toBeInTheDocument()
      const select = screen.getByLabelText('Fish S2 Pro（1人目）') as HTMLSelectElement
      expect(select).not.toBeDisabled()
      expect(select.value).toBe('old_voice')

      await user.click(screen.getByRole('button', { name: '保存する' }))
      const dialog = await screen.findByRole('dialog')
      await user.type(within(dialog).getByLabelText('変更メモ'), '一覧エラー時の保存')
      await user.click(within(dialog).getByRole('button', { name: '保存する' }))

      await waitFor(() => expect(programFetchCalls()).toHaveLength(1))
      const [, fetchOptions] = programFetchCalls()[0]
      const sentBody = JSON.parse(fetchOptions.body as string)
      expect(sentBody.cast[0].voice_fishs2pro).toBe('old_voice')
    })

    it('一覧取得がHTTPエラーの場合、エラーメッセージを表示し、画面は崩れず保存できる', async () => {
      setupFetch(
        () =>
          jsonResponse(200, {
            id: 'p1',
            name: 'テスト番組',
            kind: 'radio',
            definition: baseProgram(1),
            is_active: true,
            created_at: '',
            updated_at: '',
          }),
        { ok: false, status: 500, text: () => Promise.resolve('') },
      )
      const user = userEvent.setup()
      await renderShell({ mode: 'edit', initialProgram: baseProgram(1), initialIsActive: true, mcs: [] })

      expect(
        await screen.findByText('ボイス一覧を取得できませんでした（処理に失敗しました（status: 500））'),
      ).toBeInTheDocument()
      const select = screen.getByLabelText('Fish S2 Pro（1人目）') as HTMLSelectElement
      expect(select).not.toBeDisabled()

      await user.click(screen.getByRole('button', { name: '保存する' }))
      const dialog = await screen.findByRole('dialog')
      await user.type(within(dialog).getByLabelText('変更メモ'), 'HTTPエラー時の保存')
      await user.click(within(dialog).getByRole('button', { name: '保存する' }))

      await waitFor(() => expect(programFetchCalls()).toHaveLength(1))
    })

    it('一覧取得がネットワークエラーの場合、エラーメッセージを表示し、画面は崩れず保存できる', async () => {
      ;(global.fetch as jest.Mock).mockImplementation((url: string, options?: RequestInit) => {
        if (url === VOICE_OPTIONS_URL) return Promise.reject(new Error('network error'))
        return Promise.resolve(
          jsonResponse(200, {
            id: 'p1',
            name: 'テスト番組',
            kind: 'radio',
            definition: baseProgram(1),
            is_active: true,
            created_at: '',
            updated_at: '',
          }),
        )
      })
      const user = userEvent.setup()
      await renderShell({ mode: 'edit', initialProgram: baseProgram(1), initialIsActive: true, mcs: [] })

      expect(await screen.findByText('ボイス一覧を取得できませんでした（network error）')).toBeInTheDocument()
      const select = screen.getByLabelText('Fish S2 Pro（1人目）') as HTMLSelectElement
      expect(select).not.toBeDisabled()

      await user.click(screen.getByRole('button', { name: '保存する' }))
      const dialog = await screen.findByRole('dialog')
      await user.type(within(dialog).getByLabelText('変更メモ'), 'ネットワークエラー時の保存')
      await user.click(within(dialog).getByRole('button', { name: '保存する' }))

      await waitFor(() => expect(programFetchCalls()).toHaveLength(1))
    })
  })
})
