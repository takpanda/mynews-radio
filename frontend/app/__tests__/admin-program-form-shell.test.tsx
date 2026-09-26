import '@testing-library/jest-dom'

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminProgramFormShell from '../components/AdminProgramFormShell'
import type { ProgramDefinitionValue } from '../lib/admin-programs'

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}))

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
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

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('AdminProgramFormShell', () => {
  it('セグメントが6件のとき追加するとエラーを表示し、7件目は追加されない', async () => {
    const user = userEvent.setup()
    render(<AdminProgramFormShell mode="edit" initialProgram={baseProgram(6)} initialIsActive={true} mcs={[]} />)

    expect(screen.getByText('セグメント（6/6）')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'セグメントを追加' }))

    expect(screen.getByText('セグメントは最大6件までです')).toBeInTheDocument()
    expect(screen.getByText('セグメント（6/6）')).toBeInTheDocument()
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('編集の保存は確認ダイアログを開き、変更メモが空だと送信しない', async () => {
    const user = userEvent.setup()
    render(<AdminProgramFormShell mode="edit" initialProgram={baseProgram(1)} initialIsActive={true} mcs={[]} />)

    await user.click(screen.getByRole('button', { name: '保存する' }))
    const dialog = await screen.findByRole('dialog')

    await user.click(within(dialog).getByRole('button', { name: '保存する' }))
    expect(await within(dialog).findByText('変更メモを入力してください')).toBeInTheDocument()
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('編集の保存はキャンセルするとPUTが送信されない', async () => {
    const user = userEvent.setup()
    render(<AdminProgramFormShell mode="edit" initialProgram={baseProgram(1)} initialIsActive={true} mcs={[]} />)

    await user.click(screen.getByRole('button', { name: '保存する' }))
    const dialog = await screen.findByRole('dialog')

    await user.type(within(dialog).getByLabelText('変更メモ'), 'テストのため変更')
    await user.click(within(dialog).getByRole('button', { name: 'キャンセル' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('変更メモを入力して確定すると、cast/segments/optionsを含むPUTが送信される', async () => {
    const responseDefinition = { ...baseProgram(1), name: '更新後の番組名' }
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
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
    render(<AdminProgramFormShell mode="edit" initialProgram={baseProgram(1)} initialIsActive={true} mcs={[]} />)

    await user.click(screen.getByRole('button', { name: '保存する' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('変更メモ'), 'テストのため変更')
    await user.click(within(dialog).getByRole('button', { name: '保存する' }))

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/admin/programs/p1', expect.objectContaining({ method: 'PUT' })))
    const [, options] = (global.fetch as jest.Mock).mock.calls[0]
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
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 422,
      text: () => Promise.resolve(JSON.stringify({ detail: 'Unknown or inactive MC: radio_male' })),
    })
    const user = userEvent.setup()
    render(<AdminProgramFormShell mode="edit" initialProgram={baseProgram(1)} initialIsActive={true} mcs={[]} />)

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
    render(<AdminProgramFormShell mode="edit" initialProgram={program} initialIsActive={true} mcs={[]} />)

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
    expect(global.fetch).not.toHaveBeenCalled()

    // セグメントの種類を管理者自身が有効な値へ選び直すと保存できる
    await user.selectOptions(screen.getByDisplayValue('つなぎ（現在の種別では使用できません）'), 'news')

    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
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

    await waitFor(() => expect(global.fetch).toHaveBeenCalled())
    const [, fetchOptions] = (global.fetch as jest.Mock).mock.calls[0]
    const sentBody = JSON.parse(fetchOptions.body as string)
    expect(sentBody.kind).toBe('commentary')
    expect(sentBody.options.narrative_arc).toBe(false)
    expect(sentBody.segments[0].kind).toBe('news')
  })

  it('新規作成は確認ダイアログなしで、cast/segments/optionsを含むPOSTを送信する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
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
    render(<AdminProgramFormShell mode="create" initialProgram={created} initialIsActive={true} mcs={[]} />)

    await user.click(screen.getByRole('button', { name: '作成する' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/admin/programs', expect.objectContaining({ method: 'POST' })))

    const [, fetchOptions] = (global.fetch as jest.Mock).mock.calls[0]
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

  it('編集フォームはPCのみ、閲覧サマリーはスマホのみ表示するクラス構成になっている', () => {
    // jsdomはメディアクエリを評価しないため、実際の375px/PC幅の見え方はPlaywright等の実ブラウザ確認が必要。
    // ここでは責務分割用のコンテナ（hidden md:block / md:hidden）が外れていないことを回帰的に検知する。
    const { getByTestId } = render(
      <AdminProgramFormShell mode="edit" initialProgram={baseProgram(1)} initialIsActive={true} mcs={[]} />,
    )
    const editForm = getByTestId('program-edit-form')
    expect(editForm).toHaveClass('hidden')
    expect(editForm).toHaveClass('md:block')
    expect(within(editForm).getByRole('button', { name: '保存する' })).toBeInTheDocument()

    const mobileSummary = getByTestId('program-mobile-summary')
    expect(mobileSummary).toHaveClass('md:hidden')
    expect(within(mobileSummary).queryByRole('button', { name: '保存する' })).not.toBeInTheDocument()
  })
})
