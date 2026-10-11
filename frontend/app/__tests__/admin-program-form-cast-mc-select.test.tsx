import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminProgramFormShell from '../components/AdminProgramFormShell'
import type { Mc, ProgramCastValue, ProgramDefinitionValue } from '../lib/admin-programs'

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}))

const VOICE_OPTIONS_URL = '/api/admin/settings/voices/options'

function mc(id: string, name: string, role: string, isActive = true): Mc {
  return {
    id,
    name,
    role,
    persona: `${name}のペルソナ`,
    voice_fishs2pro: `voice_${id}`,
    voice_aivispeech: 11,
    voice_voicevox: 3,
    is_active: isActive,
    created_at: '',
    updated_at: '',
  }
}

const MCS = [mc('haru', 'ハル', 'メインMC'), mc('aki', 'アキ', 'アシスタント'), mc('mina', 'ミナ', '解説', false)]

function cast(patch: Partial<ProgramCastValue> = {}): ProgramCastValue {
  return {
    key: '',
    name: '',
    role: '',
    mc_id: null,
    voice_fishs2pro: null,
    voice_aivispeech: null,
    voice_voicevox: null,
    ...patch,
  }
}

function program(casts: ProgramCastValue[]): ProgramDefinitionValue {
  return {
    id: 'p1',
    name: 'テスト番組',
    kind: 'radio',
    cast: casts,
    segments: [],
    options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
  }
}

async function savedCast() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '作成する' }))
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/programs', expect.objectContaining({ method: 'POST' })),
  )
  const call = (global.fetch as jest.Mock).mock.calls.find(([url]) => url === '/api/admin/programs')
  return JSON.parse(call[1].body as string).cast
}

async function renderShell(casts: ProgramCastValue[]) {
  global.fetch = jest.fn((url: string) => {
    if (url === VOICE_OPTIONS_URL) {
      const empty = { status: 'ok', options: [], error: null }
      const body = { aivispeech: empty, voicevox: empty, fishs2pro: empty }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve('') })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}), text: () => Promise.resolve('{}') })
  }) as unknown as typeof fetch
  render(<AdminProgramFormShell mode="create" initialProgram={program(casts)} initialIsActive={true} mcs={MCS} />)
  await waitFor(() => expect(screen.getAllByLabelText(/^Fish S2 Pro/)[0]).not.toBeDisabled())
}

const nameSelect = (n: number) => screen.getByLabelText(`名前（${n}人目）`) as HTMLSelectElement
// LabeledInput は label と input が関連付けられていないため、ラベル直後の input を取得する
const labeledInput = (label: string, n: number) =>
  screen.getAllByText(label, { selector: 'label' })[n - 1].nextElementSibling as HTMLInputElement
const keyInput = (n: number) => labeledInput('キー', n)
const roleInput = (n: number) => labeledInput('役割', n)
const fishSelect = (n: number) => screen.getByLabelText(`Fish S2 Pro（${n}人目）`) as HTMLSelectElement

describe('AdminProgramFormShell キャスト名のMC選択', () => {
  it('MCを選ぶと名前・役割・キー・ボイスが自動入力される', async () => {
    const user = userEvent.setup()
    await renderShell([cast()])
    expect(nameSelect(1)).toHaveValue('')

    await user.selectOptions(nameSelect(1), 'haru')

    expect(nameSelect(1)).toHaveValue('haru')
    expect(keyInput(1)).toHaveValue('haru')
    expect(roleInput(1)).toHaveValue('メインMC')
    expect(fishSelect(1)).toHaveValue('voice_haru')
  })

  it('無効MCは「（無効）」付きで選べる', async () => {
    await renderShell([cast()])
    expect(screen.getAllByRole('option', { name: 'ミナ（無効）' }).length).toBeGreaterThan(0)
  })

  it('候補外の既存名はmc_idが無くても「一覧にありません」で保持される', async () => {
    await renderShell([cast({ key: 'old', name: '旧キャスト', role: '進行' })])
    expect(screen.getByRole('option', { name: '旧キャスト（一覧にありません）' })).toBeInTheDocument()
    expect(nameSelect(1).selectedOptions[0]).toHaveTextContent('旧キャスト（一覧にありません）')
  })

  it('有効なmc_idでも保存済みの名前がプロフィール名と違えば、名前を隠さず保持表示する', async () => {
    await renderShell([cast({ key: 'haru', name: '旧ハル', role: 'メインMC', mc_id: 'haru' })])
    expect(nameSelect(1).selectedOptions[0]).toHaveTextContent('旧ハル（一覧にありません）')
    // 無操作で保存しても旧名とmc_idが保持される
    const saved = await savedCast()
    expect(saved[0]).toMatchObject({ name: '旧ハル', mc_id: 'haru' })
  })

  it('名前が空で有効なmc_idの既存キャストは、MC名で補完され無操作保存でも表示と一致する', async () => {
    await renderShell([cast({ key: 'haru', name: '', role: 'メインMC', mc_id: 'haru' })])
    expect(nameSelect(1)).toHaveValue('haru')
    const saved = await savedCast()
    expect(saved[0]).toMatchObject({ name: 'ハル', mc_id: 'haru' })
  })

  it('名前がプロフィール名と一致する既存キャストはそのMCが選択される', async () => {
    await renderShell([cast({ key: 'haru', name: 'ハル', mc_id: 'haru' })])
    expect(nameSelect(1)).toHaveValue('haru')
  })

  it('未設定を選ぶと名前・役割・MC参照をクリアし、キーは維持する', async () => {
    const user = userEvent.setup()
    await renderShell([cast({ key: 'haru', name: 'ハル', role: 'メインMC', mc_id: 'haru', voice_fishs2pro: 'voice_haru' })])

    await user.selectOptions(nameSelect(1), '')

    expect(nameSelect(1)).toHaveValue('')
    expect(keyInput(1)).toHaveValue('haru')
    expect(roleInput(1)).toHaveValue('')
  })

  it('同じMCを複数行で選ぶとキーに連番が付き、手動で変更できる', async () => {
    const user = userEvent.setup()
    await renderShell([cast(), cast()])

    await user.selectOptions(nameSelect(1), 'haru')
    await user.selectOptions(nameSelect(2), 'haru')
    expect(keyInput(1)).toHaveValue('haru')
    expect(keyInput(2)).toHaveValue('haru-2')

    await user.clear(roleInput(2))
    await user.type(roleInput(2), 'ゲスト')
    await user.clear(keyInput(2))
    await user.type(keyInput(2), 'guest')
    expect(roleInput(2)).toHaveValue('ゲスト')
    expect(keyInput(2)).toHaveValue('guest')
    expect(nameSelect(2)).toHaveValue('haru')
  })

  it('保存ペイロードにkey/name/role/mc_id/voice_*が入り、personaは含まれない', async () => {
    const user = userEvent.setup()
    await renderShell([cast()])
    await user.selectOptions(nameSelect(1), 'aki')
    await user.click(screen.getByRole('button', { name: '作成する' }))

    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/admin/programs', expect.objectContaining({ method: 'POST' })),
    )
    const call = (global.fetch as jest.Mock).mock.calls.find(([url]) => url === '/api/admin/programs')
    const body = JSON.parse(call[1].body as string)
    expect(body.cast).toEqual([
      {
        key: 'aki',
        name: 'アキ',
        role: 'アシスタント',
        mc_id: 'aki',
        voice_fishs2pro: 'voice_aki',
        voice_aivispeech: 11,
        voice_voicevox: 3,
      },
    ])
  })
})
