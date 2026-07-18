import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DuplicateUrlConfirmDialog from '../components/DuplicateUrlConfirmDialog'
import type { DuplicateEpisodeInfo } from '../lib/api'

const mockEpisodes: DuplicateEpisodeInfo[] = [
  {
    id: 42,
    status: 'completed',
    type: 'commentary',
    source_url: 'https://example.com/article',
    episode_date: '2026-07-15',
    created_at: '2026-07-15T10:00:00Z',
    title: '既存の解説エピソード',
    has_script: true,
  },
  {
    id: 43,
    status: 'completed',
    type: 'commentary',
    source_url: 'https://example.com/article',
    episode_date: '2026-07-14',
    created_at: '2026-07-14T10:00:00Z',
    title: '',
    has_script: true,
  },
]

const sourceUrl = 'https://example.com/article'

describe('DuplicateUrlConfirmDialog (accessibility)', () => {
  it('ダイアログに aria-labelledby が設定されている', () => {
    render(
      <DuplicateUrlConfirmDialog
        type="duplicate-found"
        episodes={[]}
        sourceUrl="https://example.com/article"
        onCancel={jest.fn()}
        onContinue={jest.fn()}
      />
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-labelledby', 'duplicate-dialog-title')
    const heading = document.getElementById('duplicate-dialog-title')
    expect(heading).toBeInTheDocument()
    expect(heading).toHaveTextContent('URLの重複を検出しました')
  })

  it('aria-labelledby が heading の id と一致する', () => {
    render(
      <DuplicateUrlConfirmDialog
        type="search-error"
        episodes={[]}
        sourceUrl="https://example.com/article"
        onCancel={jest.fn()}
        onContinue={jest.fn()}
      />
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-labelledby', 'duplicate-dialog-title')
    const heading = document.getElementById('duplicate-dialog-title')
    expect(heading).toHaveTextContent('重複の確認に失敗しました')
  })
})

describe('DuplicateUrlConfirmDialog (duplicate-found)', () => {
  const onCancel = jest.fn()
  const onContinue = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('重複検出時にタイトルと説明を表示する', () => {
    render(
      <DuplicateUrlConfirmDialog
        type="duplicate-found"
        episodes={mockEpisodes}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    expect(screen.getByText('URLの重複を検出しました')).toBeInTheDocument()
    expect(screen.getByText(/以下のURLは既に解説済みです/)).toBeInTheDocument()
  })

  it('sourceURLを表示する', () => {
    render(
      <DuplicateUrlConfirmDialog
        type="duplicate-found"
        episodes={mockEpisodes}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    expect(screen.getByText(sourceUrl)).toBeInTheDocument()
  })

  it('既存エピソードの一覧を表示する', () => {
    render(
      <DuplicateUrlConfirmDialog
        type="duplicate-found"
        episodes={mockEpisodes}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    expect(screen.getByText('既存の解説エピソード')).toBeInTheDocument()
    expect(screen.getByText('2026-07-15')).toBeInTheDocument()
    expect(screen.getByText('2026-07-14')).toBeInTheDocument()
  })

  it('タイトルが空の場合は「エピソード #id」と表示する', () => {
    render(
      <DuplicateUrlConfirmDialog
        type="duplicate-found"
        episodes={mockEpisodes}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    expect(screen.getByText('エピソード #43')).toBeInTheDocument()
  })

  it('「中止」をクリックするとonCancelが呼ばれる', async () => {
    const user = userEvent.setup()
    render(
      <DuplicateUrlConfirmDialog
        type="duplicate-found"
        episodes={mockEpisodes}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    await user.click(screen.getByText('中止'))
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onContinue).not.toHaveBeenCalled()
  })

  it('「生成を続行」をクリックするとonContinueが呼ばれる', async () => {
    const user = userEvent.setup()
    render(
      <DuplicateUrlConfirmDialog
        type="duplicate-found"
        episodes={mockEpisodes}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    await user.click(screen.getByText('生成を続行'))
    expect(onContinue).toHaveBeenCalledTimes(1)
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('EscapeキーでonCancelが呼ばれる', async () => {
    const user = userEvent.setup()
    render(
      <DuplicateUrlConfirmDialog
        type="duplicate-found"
        episodes={mockEpisodes}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    await user.keyboard('{Escape}')
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})

describe('DuplicateUrlConfirmDialog (search-error)', () => {
  const onCancel = jest.fn()
  const onContinue = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('検索失敗時にタイトルと説明を表示する', () => {
    render(
      <DuplicateUrlConfirmDialog
        type="search-error"
        episodes={[]}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    expect(screen.getByText('重複の確認に失敗しました')).toBeInTheDocument()
    expect(screen.getByText(/重複の可能性があることをご了承ください/)).toBeInTheDocument()
  })

  it('sourceURLを表示する', () => {
    render(
      <DuplicateUrlConfirmDialog
        type="search-error"
        episodes={[]}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    expect(screen.getByText(sourceUrl)).toBeInTheDocument()
  })

  it('「中止」をクリックするとonCancelが呼ばれる', async () => {
    const user = userEvent.setup()
    render(
      <DuplicateUrlConfirmDialog
        type="search-error"
        episodes={[]}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    await user.click(screen.getByText('中止'))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('「生成を続行」をクリックするとonContinueが呼ばれる', async () => {
    const user = userEvent.setup()
    render(
      <DuplicateUrlConfirmDialog
        type="search-error"
        episodes={[]}
        sourceUrl={sourceUrl}
        onCancel={onCancel}
        onContinue={onContinue}
      />
    )
    await user.click(screen.getByText('生成を続行'))
    expect(onContinue).toHaveBeenCalledTimes(1)
  })
})
