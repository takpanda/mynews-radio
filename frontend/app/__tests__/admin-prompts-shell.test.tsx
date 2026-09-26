import '@testing-library/jest-dom'

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminPromptsShell from '../components/AdminPromptsShell'
import type { PromptTemplate } from '../lib/admin-prompts'
import type { Program } from '../lib/admin-programs'

const mockPush = jest.fn()

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}))

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

const commonTemplate: PromptTemplate = {
  id: 1,
  template_key: 'category',
  program_id: null,
  required_variables: ['categories', 'source'],
  allowed_variables: ['categories', 'source'],
  versions: [{ id: 10, version: 3, status: 'active', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-02-01T00:00:00Z' }],
}

const overrideTemplate: PromptTemplate = {
  id: 2,
  template_key: 'category',
  program_id: 'radio-test',
  required_variables: ['categories', 'source'],
  allowed_variables: ['categories', 'source'],
  versions: [],
}

const programs: Program[] = [
  {
    id: 'radio-test',
    name: 'テスト番組',
    kind: 'radio',
    definition: { id: 'radio-test', name: 'テスト番組', kind: 'radio', cast: [], segments: [], options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' } },
    is_active: true,
    created_at: '',
    updated_at: '',
  },
  {
    id: 'other-program',
    name: '別番組',
    kind: 'radio',
    definition: { id: 'other-program', name: '別番組', kind: 'radio', cast: [], segments: [], options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' } },
    is_active: true,
    created_at: '',
    updated_at: '',
  },
]

beforeEach(() => {
  jest.clearAllMocks()
  global.fetch = jest.fn()
})

describe('AdminPromptsShell', () => {
  it('共通・番組固有テンプレートを識別して現在版と更新日時を表示する', () => {
    render(<AdminPromptsShell initialTemplates={[commonTemplate, overrideTemplate]} programs={programs} />)

    expect(screen.getByText('category')).toBeInTheDocument()
    expect(screen.getByText('共通')).toBeInTheDocument()
    expect(screen.getByText('テスト番組')).toBeInTheDocument()
    expect(screen.getByText('v3')).toBeInTheDocument()
    expect(screen.getByText('2026-02-01T00:00:00Z')).toBeInTheDocument()
    expect(screen.getByText('(なし)')).toBeInTheDocument()
  })

  it('番組固有版の追加コントロールはPCのみのクラス構成になっている', () => {
    render(<AdminPromptsShell initialTemplates={[commonTemplate, overrideTemplate]} programs={programs} />)

    const addControl = screen.getByTestId('add-override-category')
    expect(addControl).toHaveClass('hidden')
    expect(addControl).toHaveClass('md:flex')
    // radio-testは既にoverrideがあるため選択肢に出ない
    expect(within(addControl).queryByText('テスト番組')).not.toBeInTheDocument()
    expect(within(addControl).getByText('別番組')).toBeInTheDocument()
  })

  it('番組を選択して追加すると作成APIを呼び、詳細ページへ遷移する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(201, { ...overrideTemplate, id: 3, program_id: 'other-program' }))
    const user = userEvent.setup()
    render(<AdminPromptsShell initialTemplates={[commonTemplate, overrideTemplate]} programs={programs} />)

    const addControl = screen.getByTestId('add-override-category')
    await user.selectOptions(within(addControl).getByLabelText('categoryの番組固有版を追加する対象番組'), 'other-program')
    await user.click(within(addControl).getByRole('button', { name: '番組固有版を追加' }))

    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/admin/prompts',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ template_key: 'category', program_id: 'other-program' }),
        }),
      ),
    )
    expect(mockPush).toHaveBeenCalledWith('/admin/prompts/3')
  })

  it('作成に失敗するとエラーを表示し遷移しない', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 409,
      text: () => Promise.resolve('Prompt template already exists'),
    })
    const user = userEvent.setup()
    render(<AdminPromptsShell initialTemplates={[commonTemplate, overrideTemplate]} programs={programs} />)

    const addControl = screen.getByTestId('add-override-category')
    await user.selectOptions(within(addControl).getByLabelText('categoryの番組固有版を追加する対象番組'), 'other-program')
    await user.click(within(addControl).getByRole('button', { name: '番組固有版を追加' }))

    expect(await within(addControl).findByText('Prompt template already exists')).toBeInTheDocument()
    expect(mockPush).not.toHaveBeenCalled()
  })
})
