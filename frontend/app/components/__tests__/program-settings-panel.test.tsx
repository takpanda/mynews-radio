import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ProgramSettingsPanel from '../ProgramSettingsPanel'

const mockFetch = jest.fn()
const mockSave = jest.fn()
const mockReset = jest.fn()

jest.mock('../../lib/api', () => ({
  fetchProgramSettings: (...args: unknown[]) => mockFetch(...args),
  saveProgramSettings: (...args: unknown[]) => mockSave(...args),
  resetProgramSettings: (...args: unknown[]) => mockReset(...args),
}))

const defaults = { priority_themes: [], excluded_themes: [], duration_preset: 'normal' as const }

describe('ProgramSettingsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockFetch.mockResolvedValue(defaults)
    mockSave.mockResolvedValue(defaults)
    mockReset.mockResolvedValue(defaults)
  })

  it('設定を読み込み、選択内容を保存する', async () => {
    const user = userEvent.setup()
    render(<ProgramSettingsPanel />)

    await waitFor(() => expect(screen.getAllByRole('button', { name: /^テクノロジー$/ })[0]).toBeEnabled())
    await user.click(screen.getAllByRole('button', { name: /^テクノロジー$/ })[0])

    await waitFor(() => expect(mockSave).toHaveBeenCalledWith({
      priority_themes: ['technology'], excluded_themes: [], duration_preset: 'normal',
    }))
    expect(screen.getByText('保存しました')).toBeInTheDocument()
  })

  it('保存失敗時に失敗値を保持し、明示的な再試行ができる', async () => {
    const user = userEvent.setup()
    mockSave.mockRejectedValueOnce(new Error('設定を保存できませんでした')).mockResolvedValueOnce({
      priority_themes: ['technology'], excluded_themes: [], duration_preset: 'normal',
    })
    render(<ProgramSettingsPanel />)

    await waitFor(() => expect(screen.getAllByRole('button', { name: /^テクノロジー$/ })[0]).toBeEnabled())
    await user.click(screen.getAllByRole('button', { name: /^テクノロジー$/ })[0])
    expect(await screen.findByText('設定を保存できませんでした')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '再試行' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '再試行' }))
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(2))
    expect(screen.getByText('保存しました')).toBeInTheDocument()
  })

  it('初期化で既定値を表示する', async () => {
    const user = userEvent.setup()
    const configured = { priority_themes: ['business' as const], excluded_themes: [], duration_preset: 'long' as const }
    mockFetch.mockResolvedValue(configured)
    mockReset.mockResolvedValue(defaults)
    render(<ProgramSettingsPanel />)

    await waitFor(() => expect(screen.getByRole('button', { name: '初期化' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: '初期化' }))
    await waitFor(() => expect(mockReset).toHaveBeenCalled())
    expect(screen.getByText('保存しました')).toBeInTheDocument()
  })

  it('401時は設定操作を無効にしてログイン導線を表示する', async () => {
    mockFetch.mockRejectedValueOnce(new Error('ログインが必要です。再度ログインしてください。'))
    const { container } = render(<ProgramSettingsPanel />)

    expect(await screen.findByText('ログインが必要です。再度ログインしてください。')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ログインする' })).toHaveAttribute('href', '/admin/login')
    expect(container.querySelector('fieldset')).toBeDisabled()
  })
})
