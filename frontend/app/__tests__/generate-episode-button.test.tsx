import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import GenerateEpisodeButton from '../components/GenerateEpisodeButton'

const mockSearchEpisodesBySourceUrl = jest.fn()
const mockGenerateEpisode = jest.fn()

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  searchEpisodesBySourceUrl: (...args: unknown[]) => mockSearchEpisodesBySourceUrl(...args),
  generateEpisode: (...args: unknown[]) => mockGenerateEpisode(...args),
  fetchEpisode: jest.fn().mockResolvedValue(null),
}))

jest.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: jest.fn() }),
}))

jest.mock('react-hot-toast', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}))

const urlInput = () => screen.getByPlaceholderText('https://example.com/article')
const submitButton = () => screen.getByRole('button', { name: /このURLで解説を生成する/ })

describe('GenerateEpisodeButton — 解説モード重複チェック', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockGenerateEpisode.mockResolvedValue({ episode_id: 100 })
    localStorage.clear()
  })

  it('重複なしで生成が開始される', async () => {
    mockSearchEpisodesBySourceUrl.mockResolvedValue([])
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/article')
    await user.click(submitButton())

    await waitFor(() => {
      expect(mockSearchEpisodesBySourceUrl).toHaveBeenCalledWith('https://example.com/article')
    })
    await waitFor(() => {
      expect(mockGenerateEpisode).toHaveBeenCalled()
    })
  })

  it('重複ありの場合、確認ダイアログが表示され「生成を続行」で生成が開始される', async () => {
    mockSearchEpisodesBySourceUrl.mockResolvedValue([
      { id: 42, title: '既存解説', status: 'completed', type: 'commentary', source_url: 'https://example.com/article', episode_date: '2026-07-15', created_at: '', has_script: true },
    ])
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/article')
    await user.click(submitButton())

    await waitFor(() => {
      expect(screen.getByText('URLの重複を検出しました')).toBeInTheDocument()
    })

    expect(mockGenerateEpisode).not.toHaveBeenCalled()

    await user.click(screen.getByText('生成を続行'))

    await waitFor(() => {
      expect(mockGenerateEpisode).toHaveBeenCalled()
    })
  })

  it('重複ありの場合「中止」でダイアログが閉じ生成が開始されない', async () => {
    mockSearchEpisodesBySourceUrl.mockResolvedValue([
      { id: 42, title: '既存解説', status: 'completed', type: 'commentary', source_url: 'https://example.com/article', episode_date: '2026-07-15', created_at: '', has_script: true },
    ])
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/article')
    await user.click(submitButton())

    await waitFor(() => {
      expect(screen.getByText('URLの重複を検出しました')).toBeInTheDocument()
    })

    await user.click(screen.getByText('中止'))

    expect(mockGenerateEpisode).not.toHaveBeenCalled()
    expect(screen.queryByText('URLの重複を検出しました')).not.toBeInTheDocument()
  })

  it('検索失敗時にエラーダイアログが表示され「生成を続行」で生成が開始される', async () => {
    mockSearchEpisodesBySourceUrl.mockRejectedValue(new Error('Network error'))
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/article')
    await user.click(submitButton())

    await waitFor(() => {
      expect(screen.getByText('重複の確認に失敗しました')).toBeInTheDocument()
    })

    expect(mockGenerateEpisode).not.toHaveBeenCalled()

    await user.click(screen.getByText('生成を続行'))

    await waitFor(() => {
      expect(mockGenerateEpisode).toHaveBeenCalled()
    })
  })

  it('検索失敗時に「中止」でダイアログが閉じ生成が開始されない', async () => {
    mockSearchEpisodesBySourceUrl.mockRejectedValue(new Error('Network error'))
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/article')
    await user.click(submitButton())

    await waitFor(() => {
      expect(screen.getByText('重複の確認に失敗しました')).toBeInTheDocument()
    })

    await user.click(screen.getByText('中止'))

    expect(mockGenerateEpisode).not.toHaveBeenCalled()
  })
})

describe('GenerateEpisodeButton — パラメータすり替え防止', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockGenerateEpisode.mockResolvedValue({ episode_id: 100 })
    localStorage.clear()
  })

  it('検索中にURLが変更されても続行時は検索開始時のURLで生成される', async () => {
    let resolveSearch!: (value: unknown) => void
    mockSearchEpisodesBySourceUrl.mockReturnValue(new Promise((resolve) => { resolveSearch = resolve }))
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/original')
    await user.click(submitButton())

    await user.clear(urlInput())
    await user.type(urlInput(), 'https://example.com/changed')

    resolveSearch([
      { id: 42, title: '既存解説', status: 'completed', type: 'commentary', source_url: 'https://example.com/original', episode_date: '2026-07-15', created_at: '', has_script: true },
    ])

    await waitFor(() => {
      expect(screen.getByText('URLの重複を検出しました')).toBeInTheDocument()
    })

    expect(screen.getByText('https://example.com/original')).toBeInTheDocument()
    expect(screen.queryByText('https://example.com/changed')).not.toBeInTheDocument()

    await user.click(screen.getByText('生成を続行'))

    await waitFor(() => {
      expect(mockGenerateEpisode).toHaveBeenCalled()
    })

    const args = mockGenerateEpisode.mock.calls[0]
    expect(args[5]).toBe('https://example.com/original')
  })

  it('検索中にスタイルが変更されても続行時は検索開始時のスタイルで生成される', async () => {
    let resolveSearch!: (value: unknown) => void
    mockSearchEpisodesBySourceUrl.mockReturnValue(new Promise((resolve) => { resolveSearch = resolve }))
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/article')
    await user.click(screen.getByText('対談解説'))
    await user.click(submitButton())

    await user.click(screen.getByText('一人解説'))

    resolveSearch([
      { id: 42, title: '既存解説', status: 'completed', type: 'commentary', source_url: 'https://example.com/article', episode_date: '2026-07-15', created_at: '', has_script: true },
    ])

    await waitFor(() => {
      expect(screen.getByText('URLの重複を検出しました')).toBeInTheDocument()
    })

    await user.click(screen.getByText('生成を続行'))

    await waitFor(() => {
      expect(mockGenerateEpisode).toHaveBeenCalled()
    })

    const args = mockGenerateEpisode.mock.calls[0]
    expect(args[6]).toBe('dialogue')
  })

  it('検索中にURLを空にしても、続行時は解説モードのパラメータが維持される（通常モードに切り替わらない）', async () => {
    let resolveSearch!: (value: unknown) => void
    mockSearchEpisodesBySourceUrl.mockReturnValue(new Promise((resolve) => { resolveSearch = resolve }))
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/article')
    await user.click(submitButton())

    await user.clear(urlInput())

    resolveSearch([
      { id: 42, title: '既存解説', status: 'completed', type: 'commentary', source_url: 'https://example.com/article', episode_date: '2026-07-15', created_at: '', has_script: true },
    ])

    await waitFor(() => {
      expect(screen.getByText('URLの重複を検出しました')).toBeInTheDocument()
    })

    await user.click(screen.getByText('生成を続行'))

    await waitFor(() => {
      expect(mockGenerateEpisode).toHaveBeenCalled()
    })

    const args = mockGenerateEpisode.mock.calls[0]
    expect(args[5]).toBe('https://example.com/article')
  })

  it('検索失敗後も続行時は検索開始時のパラメータが使われる', async () => {
    let rejectSearch!: (reason: unknown) => void
    mockSearchEpisodesBySourceUrl.mockReturnValue(new Promise((_, reject) => { rejectSearch = reject }))
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/article')
    await user.click(submitButton())

    await user.clear(urlInput())
    await user.type(urlInput(), 'https://example.com/different')

    rejectSearch(new Error('Network error'))

    await waitFor(() => {
      expect(screen.getByText('重複の確認に失敗しました')).toBeInTheDocument()
    })

    await user.click(screen.getByText('生成を続行'))

    await waitFor(() => {
      expect(mockGenerateEpisode).toHaveBeenCalled()
    })

    const args = mockGenerateEpisode.mock.calls[0]
    expect(args[5]).toBe('https://example.com/article')
  })

  it('検索中に全パラメータを変更しても続行時はスナップショット値が固定される（newsSource含む）', async () => {
    let resolveSearch!: (value: unknown) => void
    mockSearchEpisodesBySourceUrl.mockReturnValue(new Promise((resolve) => { resolveSearch = resolve }))
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    await user.type(urlInput(), 'https://example.com/original')
    await user.click(submitButton())

    await user.clear(urlInput())
    await user.type(urlInput(), 'https://example.com/changed')
    await user.click(screen.getByText('対談解説'))
    await user.click(screen.getByText('VOICEVOX'))

    resolveSearch([
      { id: 42, title: '既存解説', status: 'completed', type: 'commentary', source_url: 'https://example.com/original', episode_date: '2026-07-15', created_at: '', has_script: true },
    ])

    await waitFor(() => {
      expect(screen.getByText('URLの重複を検出しました')).toBeInTheDocument()
    })

    await user.click(screen.getByText('生成を続行'))

    await waitFor(() => {
      expect(mockGenerateEpisode).toHaveBeenCalled()
    })

    const args = mockGenerateEpisode.mock.calls[0]
    expect(args[0]).toBeDefined()
    expect(args[1]).toBe(10)
    expect(args[2]).toBe('hatena_bookmark')
    expect(args[3]).toBe('aivispeech')
    expect(args[4]).toBe(false)
    expect(args[5]).toBe('https://example.com/original')
    expect(args[6]).toBe('solo')
    expect(args[7]).toBe('male')
  })
})

describe('GenerateEpisodeButton — 通常ラジオ生成（回帰）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockGenerateEpisode.mockResolvedValue({ episode_id: 100 })
    localStorage.clear()
  })

  it('URL未入力の通常モードでは重複チェックを行わず生成を開始する', async () => {
    const user = userEvent.setup()

    render(<GenerateEpisodeButton />)

    const radioButton = screen.getByText('この設定で番組を生成する')
    await user.click(radioButton)

    await waitFor(() => {
      expect(mockGenerateEpisode).toHaveBeenCalled()
    })
    expect(mockSearchEpisodesBySourceUrl).not.toHaveBeenCalled()
  })
})
