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
})
