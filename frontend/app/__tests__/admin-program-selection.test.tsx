import '@testing-library/jest-dom'

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminProgramFormShell from '../components/AdminProgramFormShell'
import type { ProgramDefinitionValue } from '../lib/admin-programs'

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

function program(extra: Partial<ProgramDefinitionValue> = {}): ProgramDefinitionValue {
  return {
    id: 'p1',
    name: 'テスト番組',
    kind: 'radio',
    cast: [
      {
        key: 'male',
        name: '田村',
        role: 'メインMC',
        mc_id: null,
        persona: 'サーバーが解決した人物設定',
        voice_fishs2pro: null,
        voice_aivispeech: null,
        voice_voicevox: null,
      },
    ],
    segments: [],
    options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
    ...extra,
  }
}

function programCalls() {
  return (global.fetch as jest.Mock).mock.calls.filter(([url]) => url !== VOICE_OPTIONS_URL)
}

async function renderShell(initialProgram: ProgramDefinitionValue) {
  render(<AdminProgramFormShell mode="edit" initialProgram={initialProgram} initialIsActive mcs={[]} />)
  await waitFor(() => expect(screen.getAllByLabelText(/^Fish S2 Pro/)[0]).not.toBeDisabled())
}

async function save(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: '保存する' }))
  const dialog = await screen.findByRole('dialog')
  await user.type(within(dialog).getByLabelText('変更メモ'), 'テスト')
  await user.click(within(dialog).getByRole('button', { name: '保存する' }))
}

beforeEach(() => {
  global.fetch = jest.fn().mockImplementation((url: string) => {
    if (url === VOICE_OPTIONS_URL) {
      return Promise.resolve(
        jsonResponse(200, {
          aivispeech: { status: 'ok', options: [], error: null },
          voicevox: { status: 'ok', options: [], error: null },
          fishs2pro: { status: 'ok', options: [], error: null },
        }),
      )
    }
    return Promise.resolve(jsonResponse(200, { id: 'p1', name: 'n', kind: 'radio', definition: program(), is_active: true, created_at: '', updated_at: '' }))
  })
})

describe('AdminProgramFormShell ソース・選定ルール', () => {
  it('未設定の番組では「従来設定を使う」が選ばれ、保存ではnullを送る（persona は送らない）', async () => {
    const user = userEvent.setup()
    await renderShell(program())

    expect(screen.getByLabelText('ニュースソース')).toHaveValue('')
    expect(screen.getByLabelText('尺プリセット')).toHaveValue('')
    await save(user)

    await waitFor(() => expect(programCalls()).toHaveLength(1))
    const body = JSON.parse(programCalls()[0][1].body as string)
    expect(body).toMatchObject({
      news_source: null,
      priority_themes: null,
      excluded_themes: null,
      max_articles: null,
      min_importance_score: null,
      duration_preset: null,
    })
    expect(body.cast[0]).not.toHaveProperty('persona')
  })

  it('保存済みの値が再表示され、変更した値がPUTに含まれる', async () => {
    const user = userEvent.setup()
    await renderShell(
      program({
        news_source: 'hatena_bookmark',
        priority_themes: ['technology'],
        excluded_themes: ['sports'],
        max_articles: 10,
        min_importance_score: 3,
        duration_preset: 'long',
      }),
    )

    expect(screen.getByLabelText('ニュースソース')).toHaveValue('hatena_bookmark')
    expect(screen.getByLabelText('尺プリセット')).toHaveValue('long')
    expect(screen.getByLabelText('記事の件数（1〜50）')).toHaveValue(10)
    expect(screen.getByLabelText('最低重要度（1〜5）')).toHaveValue('3')

    await user.selectOptions(screen.getByLabelText('尺プリセット'), 'short')
    await user.clear(screen.getByLabelText('記事の件数（1〜50）'))
    await user.type(screen.getByLabelText('記事の件数（1〜50）'), '20')
    await user.click(screen.getAllByRole('checkbox', { name: 'ビジネス' })[0])
    await save(user)

    await waitFor(() => expect(programCalls()).toHaveLength(1))
    const body = JSON.parse(programCalls()[0][1].body as string)
    expect(body).toMatchObject({
      news_source: 'hatena_bookmark',
      priority_themes: ['technology', 'business'],
      excluded_themes: ['sports'],
      max_articles: 20,
      min_importance_score: 3,
      duration_preset: 'short',
    })
  })

  it('尺プリセットを未設定に戻せる', async () => {
    const user = userEvent.setup()
    await renderShell(program({ duration_preset: 'long' }))

    await user.selectOptions(screen.getByLabelText('尺プリセット'), '')
    await save(user)

    await waitFor(() => expect(programCalls()).toHaveLength(1))
    expect(JSON.parse(programCalls()[0][1].body as string).duration_preset).toBeNull()
  })

  it.each([
    ['優先テーマが4件', program({ priority_themes: ['technology', 'business', 'society', 'sports'] }), '優先テーマは最大3件までです'],
    ['優先と除外が重複', program({ priority_themes: ['technology'], excluded_themes: ['technology'] }), '同じテーマ（テクノロジー）'],
    ['件数が範囲外', program({ max_articles: 51 }), '記事の件数は1〜50の整数で入力してください'],
    ['ラジオでURLソース', program({ news_source: 'url' }), 'URL指定のニュースソースは解説番組のみ選べます'],
    ['解説で非URLソース', program({ kind: 'commentary', news_source: 'yahoo_news' }), '解説番組のニュースソースはURL指定のみ選べます'],
  ])('不正入力（%s）ではエラーを表示し送信しない', async (_label, def, message) => {
    const user = userEvent.setup()
    await renderShell(def)

    await user.click(screen.getByRole('button', { name: '保存する' }))

    expect(await screen.findByText(new RegExp(message))).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(programCalls()).toHaveLength(0)
  })
})
