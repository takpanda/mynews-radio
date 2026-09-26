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

  it('変更メモを入力して確定するとPUTが送信される', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
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
    render(<AdminProgramFormShell mode="edit" initialProgram={baseProgram(1)} initialIsActive={true} mcs={[]} />)

    await user.click(screen.getByRole('button', { name: '保存する' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('変更メモ'), 'テストのため変更')
    await user.click(within(dialog).getByRole('button', { name: '保存する' }))

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/admin/programs/p1', expect.objectContaining({ method: 'PUT' })))
  })

  it('新規作成は確認ダイアログなしでPOSTを送信する', async () => {
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
  })
})
