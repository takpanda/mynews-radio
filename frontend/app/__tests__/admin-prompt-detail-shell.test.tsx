import '@testing-library/jest-dom'

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminPromptDetailShell from '../components/AdminPromptDetailShell'
import type { PromptVersionDetail } from '../lib/admin-prompts'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

const initialVersions: PromptVersionDetail[] = [
  { id: 10, version: 2, content: '{categories}を選んでください: {source}', status: 'active', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-02-01T00:00:00Z' },
  { id: 9, version: 1, content: 'old content', status: 'archived', created_at: '2025-12-01T00:00:00Z', updated_at: '2025-12-01T00:00:00Z' },
]

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('AdminPromptDetailShell', () => {
  it('必須変数・使用可能な変数と対象（番組固有）を表示する', () => {
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId="radio-test"
        programName="テスト番組"
        programKind="radio"
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    expect(screen.getByText('category')).toBeInTheDocument()
    expect(screen.getByText('テスト番組')).toBeInTheDocument()
    expect(screen.getAllByText('categories, source')).toHaveLength(2)
  })

  it('過去版の本文を表示・非表示できる', async () => {
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    expect(screen.queryByText('old content')).not.toBeInTheDocument()
    const toggles = screen.getAllByRole('button', { name: '本文を表示' })
    await user.click(toggles[1])
    expect(screen.getByText('old content')).toBeInTheDocument()
  })

  it('変数ボタンをクリックするとカーソル位置へ変数が挿入される', async () => {
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={[]}
      />,
    )

    const textarea = screen.getByLabelText('プロンプト本文') as HTMLTextAreaElement
    await user.type(textarea, 'ここに挿入: ')
    await user.click(screen.getByRole('button', { name: '{categories}' }))

    expect(textarea.value).toBe('ここに挿入: {categories}')
  })

  it('保存に成功すると版履歴が更新され、本文はそのまま残る', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(jsonResponse(201, { id: 11, template_id: 1, version: 3, content: 'new draft content', status: 'draft' }))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          prompt_id: 1,
          template_key: 'category',
          program_id: null,
          versions: [
            { id: 11, version: 3, content: 'new draft content', status: 'draft', created_at: '2026-03-01T00:00:00Z', updated_at: '2026-03-01T00:00:00Z' },
            ...initialVersions,
          ],
        }),
      )
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    const textarea = screen.getByLabelText('プロンプト本文') as HTMLTextAreaElement
    await user.clear(textarea)
    await user.type(textarea, 'new draft content')
    await user.click(screen.getByRole('button', { name: '下書きとして保存' }))

    await waitFor(() =>
      expect(global.fetch).toHaveBeenNthCalledWith(
        1,
        '/api/admin/prompts/1/versions',
        expect.objectContaining({ method: 'POST', body: JSON.stringify({ content: 'new draft content' }) }),
      ),
    )
    expect(await screen.findByText('v3')).toBeInTheDocument()
    expect(textarea.value).toBe('new draft content')
  })

  it('版作成が成功し履歴の再取得だけが失敗しても、保存失敗とは表示せず作成済みの版を一覧へ反映する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(jsonResponse(201, { id: 11, template_id: 1, version: 3, content: 'new draft content', status: 'draft' }))
      .mockResolvedValueOnce({ ok: false, status: 500, text: () => Promise.resolve('') })
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    const textarea = screen.getByLabelText('プロンプト本文') as HTMLTextAreaElement
    await user.clear(textarea)
    await user.type(textarea, 'new draft content')
    await user.click(screen.getByRole('button', { name: '下書きとして保存' }))

    // 版の作成(POST)自体は成功しているため、履歴の再取得(GET)失敗を保存失敗として表示しない。
    // 再送信による重複した下書き版の作成を避けるため、作成済みの版を一覧へ反映する。
    expect(await screen.findByText('v3')).toBeInTheDocument()
    expect(screen.queryByText('保存に失敗しました')).not.toBeInTheDocument()
    expect(textarea.value).toBe('new draft content')
    expect(screen.getByRole('button', { name: '下書きとして保存' })).not.toBeDisabled()
  })

  it('422応答時はエラーを表示し、入力した本文を失わない', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 422,
      text: () => Promise.resolve(JSON.stringify({ detail: 'Missing required variables: source' })),
    })
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={[]}
      />,
    )

    const textarea = screen.getByLabelText('プロンプト本文') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '{categories}のみで送信' } })
    await user.click(screen.getByRole('button', { name: '下書きとして保存' }))

    expect(await screen.findByText('Missing required variables: source')).toBeInTheDocument()
    expect(textarea.value).toBe('{categories}のみで送信')
  })

  it('編集フォームはPCのみ、閲覧情報・版履歴はスマホでも表示するクラス構成になっている', () => {
    const { getByTestId } = render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    const editForm = getByTestId('prompt-edit-form')
    expect(editForm).toHaveClass('hidden')
    expect(editForm).toHaveClass('md:block')
    expect(within(editForm).getByRole('button', { name: '下書きとして保存' })).toBeInTheDocument()

    const mobileNote = getByTestId('prompt-mobile-note')
    expect(mobileNote).toHaveClass('md:hidden')

    expect(screen.getByText('v2')).toBeInTheDocument()
  })

  it('過去版と現在版の差分を表示できる', async () => {
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    await user.click(screen.getByRole('button', { name: '現在版との差分を見る' }))
    // 差分は「現在版 → この版」の向きで表示する（このアーカイブ版に戻すと何が変わるか）
    const diffView = screen.getByTestId('diff-view')
    expect(within(diffView).getByText('+', { exact: false })).toHaveTextContent('old content')
    expect(within(diffView).getByText('-', { exact: false })).toHaveTextContent(
      '{categories}を選んでください: {source}',
    )
  })

  it('過去回IDを指定して展開プレビューを実行できる', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(200, { version_id: 9, episode_id: 5, template_key: 'category', prompt: '展開後の本文' }),
    )
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    const inputs = screen.getAllByLabelText(/の展開プレビュー用過去回ID/)
    await user.type(inputs[1], '5')
    await user.click(screen.getAllByRole('button', { name: 'この版で展開プレビューを実行' })[1])

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/admin/prompts/versions/9/render',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ episode_id: 5 }) }),
    )
    expect(await screen.findByText('展開後の本文')).toBeInTheDocument()
    expect(screen.getByText('対象の過去回ID: 5')).toBeInTheDocument()
  })

  it('過去回IDを変更すると表示中の展開プレビュー結果が破棄される', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(200, { version_id: 9, episode_id: 5, template_key: 'category', prompt: '展開後の本文' }),
    )
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    const inputs = screen.getAllByLabelText(/の展開プレビュー用過去回ID/)
    await user.type(inputs[1], '5')
    await user.click(screen.getAllByRole('button', { name: 'この版で展開プレビューを実行' })[1])
    expect(await screen.findByText('展開後の本文')).toBeInTheDocument()

    // 表示中の結果と入力中のIDが食い違って別回の結果を取り違えないよう、ID変更時は前回の結果を破棄する
    await user.type(inputs[1], '6')
    expect(screen.queryByText('展開後の本文')).not.toBeInTheDocument()
    expect(screen.queryByText(/対象の過去回ID/)).not.toBeInTheDocument()
  })

  it('通信中に過去回IDを変更すると、変更前のリクエストへの遅延応答は結果に反映されない', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined
    ;(global.fetch as jest.Mock)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve
          }),
      )
      .mockResolvedValueOnce(
        jsonResponse(200, { version_id: 9, episode_id: 6, template_key: 'category', prompt: '6回目の本文' }),
      )
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    const inputs = screen.getAllByLabelText(/の展開プレビュー用過去回ID/)
    await user.type(inputs[1], '5')
    await user.click(screen.getAllByRole('button', { name: 'この版で展開プレビューを実行' })[1])

    // ID=5への応答がまだ届かないうちにIDを変更し、ID=6で改めて実行する
    await user.clear(inputs[1])
    await user.type(inputs[1], '6')
    await user.click(screen.getAllByRole('button', { name: 'この版で展開プレビューを実行' })[1])
    expect(await screen.findByText('6回目の本文')).toBeInTheDocument()

    // ID=5への遅延応答が今ごろ届いても、既に表示中のID=6の結果を上書きしない
    resolveFirst?.(jsonResponse(200, { version_id: 9, episode_id: 5, template_key: 'category', prompt: '5回目の本文' }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.getByText('6回目の本文')).toBeInTheDocument()
    expect(screen.queryByText('5回目の本文')).not.toBeInTheDocument()
    expect(screen.getByText('対象の過去回ID: 6')).toBeInTheDocument()
  })

  it('番組固有テンプレートでは対象番組の現在の運用結果も確認できる', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(200, { program_id: 'radio-test', episode_id: 5, template_key: 'category', version_id: 10, prompt: '運用中の本文' }),
    )
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId="radio-test"
        programName="テスト番組"
        programKind="radio"
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    const inputs = screen.getAllByLabelText(/の展開プレビュー用過去回ID/)
    await user.type(inputs[0], '5')
    await user.click(screen.getAllByRole('button', { name: '対象番組の現在の運用結果を確認' })[0])

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/admin/programs/radio-test/preview-prompt',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ template_key: 'category', episode_id: 5 }) }),
    )
    expect(await screen.findByText('対象の過去回ID: 5 ・ 運用中の版: v10')).toBeInTheDocument()
    expect(await screen.findByText('運用中の本文')).toBeInTheDocument()
  })

  it('generate_radio_script以外のテンプレートでは下書きからのテスト生成が不可の理由を表示する', () => {
    const draftOnly: PromptVersionDetail[] = [
      { id: 20, version: 1, content: 'draft body', status: 'draft', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ]
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={draftOnly}
      />,
    )

    expect(screen.getByText('テスト生成は generate_radio_script の下書き版のみ対応しています')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'テスト生成・比較テスト画面へ' })).not.toBeInTheDocument()
  })

  it('番組固有のgenerate_radio_script下書きからテスト生成画面へ版IDを引き継いで遷移できる', () => {
    const draftOnly: PromptVersionDetail[] = [
      { id: 30, version: 1, content: 'draft body', status: 'draft', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ]
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="generate_radio_script"
        programId="radio-test"
        programName="テスト番組"
        programKind="radio"
        radioPrograms={[]}
        requiredVariables={['summaries_json']}
        allowedVariables={['summaries_json']}
        initialVersions={draftOnly}
      />,
    )

    const link = screen.getByRole('link', { name: 'テスト生成・比較テスト画面へ' })
    expect(link).toHaveAttribute('href', '/admin/programs/radio-test/dry-run?draft_prompt_version_id=30')
  })

  it('共通のgenerate_radio_script下書きは対象番組を選ぶまでテスト生成画面へ進めない', async () => {
    const draftOnly: PromptVersionDetail[] = [
      { id: 40, version: 1, content: 'draft body', status: 'draft', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ]
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="generate_radio_script"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[{ id: 'radio-a', name: 'ラジオA' }]}
        requiredVariables={['summaries_json']}
        allowedVariables={['summaries_json']}
        initialVersions={draftOnly}
      />,
    )

    expect(screen.getByText('対象番組を選択してください')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'テスト生成・比較テスト画面へ' })).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('テスト生成の対象番組'), 'radio-a')
    const link = screen.getByRole('link', { name: 'テスト生成・比較テスト画面へ' })
    expect(link).toHaveAttribute('href', '/admin/programs/radio-a/dry-run?draft_prompt_version_id=40')
  })

  it('対象番組一覧の取得に失敗した場合は選択UIではなく取得失敗を表示する', () => {
    const draftOnly: PromptVersionDetail[] = [
      { id: 40, version: 1, content: 'draft body', status: 'draft', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ]
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="generate_radio_script"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        radioProgramsError
        requiredVariables={['summaries_json']}
        allowedVariables={['summaries_json']}
        initialVersions={draftOnly}
      />,
    )

    expect(screen.getByText('対象番組一覧の取得に失敗しました。画面を再読み込みしてください。')).toBeInTheDocument()
    expect(screen.queryByLabelText('テスト生成の対象番組')).not.toBeInTheDocument()
  })

  it('テスト生成に使えるradio番組が0件の場合は取得失敗と区別して案内する', () => {
    const draftOnly: PromptVersionDetail[] = [
      { id: 40, version: 1, content: 'draft body', status: 'draft', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ]
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="generate_radio_script"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['summaries_json']}
        allowedVariables={['summaries_json']}
        initialVersions={draftOnly}
      />,
    )

    expect(screen.getByText('テスト生成に使えるradio番組が登録されていません')).toBeInTheDocument()
    expect(screen.queryByLabelText('テスト生成の対象番組')).not.toBeInTheDocument()
  })

  it('本番適用・ロールバックのボタンはPCのみ表示するクラス構成になっている', () => {
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    const activateButton = screen.getByRole('button', { name: 'この版へロールバック' })
    expect(activateButton.parentElement).toHaveClass('hidden')
    expect(activateButton.parentElement).toHaveClass('md:block')
  })

  it('空の変更メモでは適用操作を送信できない', async () => {
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    // active版(v2)ではなくarchived版(v1)のロールバックで確認する
    await user.click(screen.getByRole('button', { name: 'この版へロールバック' }))
    const submit = screen.getByRole('button', { name: 'ロールバックする' })
    expect(submit).toBeDisabled()
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('本番適用に成功すると版履歴を再取得して結果を表示する', async () => {
    const draftVersions: PromptVersionDetail[] = [
      { id: 11, version: 3, content: 'new content', status: 'draft', created_at: '2026-03-01T00:00:00Z', updated_at: '2026-03-01T00:00:00Z' },
      ...initialVersions,
    ]
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(jsonResponse(200, { id: 11, status: 'active', previous_active_version_id: 10 }))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          prompt_id: 1,
          template_key: 'category',
          program_id: null,
          versions: [
            { id: 11, version: 3, content: 'new content', status: 'active', created_at: '2026-03-01T00:00:00Z', updated_at: '2026-03-02T00:00:00Z' },
            { id: 10, version: 2, content: '{categories}を選んでください: {source}', status: 'archived', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-03-02T00:00:00Z' },
            initialVersions[1],
          ],
        }),
      )
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={draftVersions}
      />,
    )

    await user.click(screen.getByRole('button', { name: '本番適用' }))
    await user.type(screen.getByLabelText('変更メモ'), '文言を調整')
    await user.click(screen.getByRole('button', { name: '適用する' }))

    await waitFor(() =>
      expect(global.fetch).toHaveBeenNthCalledWith(
        1,
        '/api/admin/prompts/versions/11/activate',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ change_note: '文言を調整', expected_active_version_id: 10 }),
        }),
      ),
    )
    await waitFor(() => expect(screen.queryByRole('button', { name: '適用する' })).not.toBeInTheDocument())
    expect(await screen.findByText('公開中')).toBeInTheDocument()
  })

  it('本番適用で409が返るとエラーと再取得の案内を表示する', async () => {
    const draftVersions: PromptVersionDetail[] = [
      { id: 11, version: 3, content: 'new content', status: 'draft', created_at: '2026-03-01T00:00:00Z', updated_at: '2026-03-01T00:00:00Z' },
      ...initialVersions,
    ]
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 409,
      text: () => Promise.resolve(JSON.stringify({ detail: 'Active prompt version has changed' })),
    })
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={draftVersions}
      />,
    )

    await user.click(screen.getByRole('button', { name: '本番適用' }))
    await user.type(screen.getByLabelText('変更メモ'), '文言を調整')
    await user.click(screen.getByRole('button', { name: '適用する' }))

    expect(await screen.findByText('現在版が更新されています。最新の状態を取得してください。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '最新の状態を取得' })).toBeInTheDocument()
  })

  it('ロールバックに成功すると新しい版の作成を反映したメッセージで案内する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(
        jsonResponse(200, { id: 12, version: 3, status: 'active', rollback_from_version_id: 9, previous_active_version_id: 10 }),
      )
      .mockResolvedValueOnce(
        jsonResponse(200, {
          prompt_id: 1,
          template_key: 'category',
          program_id: null,
          versions: [
            { id: 12, version: 3, content: 'old content', status: 'active', created_at: '2025-12-01T00:00:00Z', updated_at: '2026-04-01T00:00:00Z' },
            { id: 10, version: 2, content: '{categories}を選んでください: {source}', status: 'archived', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-04-01T00:00:00Z' },
            { id: 9, version: 1, content: 'old content', status: 'archived', created_at: '2025-12-01T00:00:00Z', updated_at: '2025-12-01T00:00:00Z' },
          ],
        }),
      )
    const user = userEvent.setup()
    render(
      <AdminPromptDetailShell
        promptId={1}
        templateKey="category"
        programId={null}
        programName={null}
        programKind={null}
        radioPrograms={[]}
        requiredVariables={['categories', 'source']}
        allowedVariables={['categories', 'source']}
        initialVersions={initialVersions}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'この版へロールバック' }))
    await user.type(screen.getByLabelText('変更メモ'), '不具合のため戻す')
    await user.click(screen.getByRole('button', { name: 'ロールバックする' }))

    await waitFor(() =>
      expect(global.fetch).toHaveBeenNthCalledWith(
        1,
        '/api/admin/prompts/versions/9/rollback',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ change_note: '不具合のため戻す', expected_active_version_id: 10 }),
        }),
      ),
    )
    expect(await screen.findByText('v3')).toBeInTheDocument()
  })
})
