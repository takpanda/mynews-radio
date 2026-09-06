import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CategoryFemaleMcSection from '../CategoryFemaleMcSection'
import type { CategoryFemaleMcSettings } from '../../lib/admin-category-female-mc'

const mockFetch = jest.fn()
jest.mock('../../lib/admin-category-female-mc', () => {
  const actual = jest.requireActual('../../lib/admin-category-female-mc')
  return {
    ...actual,
    fetchCategoryFemaleMcClient: (...args: unknown[]) => mockFetch(...args),
  }
})

const sampleData: CategoryFemaleMcSettings = {
  categories: ['テック・IT'],
  category_female_voices: { 'テック・IT': null },
  default_voice: 'morigawa',
  voices: [
    {
      display_name: 'morigawa',
      value: 'morigawa',
      sample: {
        url: '/api/admin/settings/voices/categories/samples/morigawa',
        text: 'サンプル文',
        media_type: 'audio/wav',
        available: true,
      },
    },
  ],
}

beforeEach(() => {
  jest.clearAllMocks()
})

describe('CategoryFemaleMcSection', () => {
  it('初期取得成功：カテゴリ別女性MC設定パネルが表示される', () => {
    render(<CategoryFemaleMcSection initialData={sampleData} initialError={null} />)
    expect(screen.getByText('カテゴリ別女性MC設定')).toBeInTheDocument()
  })

  it('初期取得失敗：エラーメッセージと再試行ボタンが表示される', () => {
    render(<CategoryFemaleMcSection initialData={null} initialError="カテゴリ別女性MC設定を取得できませんでした。しばらく後でもう一度お試しください。" />)
    expect(screen.getByRole('alert')).toHaveTextContent('カテゴリ別女性MC設定を取得できませんでした。しばらく後でもう一度お試しください。')
    expect(screen.getByRole('button', { name: 'カテゴリ別女性MC設定を再試行' })).toBeInTheDocument()
    expect(screen.queryByText('カテゴリ別女性MC設定')).not.toBeInTheDocument()
  })

  it('再試行成功：取得できたデータでパネルが表示される', async () => {
    mockFetch.mockResolvedValueOnce(sampleData)
    const user = userEvent.setup()
    render(<CategoryFemaleMcSection initialData={null} initialError="取得できませんでした" />)

    await user.click(screen.getByRole('button', { name: 'カテゴリ別女性MC設定を再試行' }))

    await waitFor(() => {
      expect(screen.getByText('カテゴリ別女性MC設定')).toBeInTheDocument()
    })
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })

  it('再試行失敗：エラーメッセージが更新され再試行ボタンは残る', async () => {
    mockFetch.mockRejectedValueOnce(new Error('保存できませんでした。しばらく後でもう一度お試しください。'))
    const user = userEvent.setup()
    render(<CategoryFemaleMcSection initialData={null} initialError="取得できませんでした" />)

    await user.click(screen.getByRole('button', { name: 'カテゴリ別女性MC設定を再試行' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('保存できませんでした。しばらく後でもう一度お試しください。')
    })
    expect(screen.getByRole('button', { name: 'カテゴリ別女性MC設定を再試行' })).toBeInTheDocument()
  })

  it('再試行中は再試行ボタンが無効化され1回しか呼ばれない', async () => {
    let resolveFetch: (value: CategoryFemaleMcSettings) => void = () => {}
    mockFetch.mockImplementationOnce(
      () => new Promise<CategoryFemaleMcSettings>((resolve) => { resolveFetch = resolve }),
    )
    const user = userEvent.setup()
    render(<CategoryFemaleMcSection initialData={null} initialError="取得できませんでした" />)

    const button = screen.getByRole('button', { name: 'カテゴリ別女性MC設定を再試行' })
    await user.click(button)
    expect(screen.getByRole('button', { name: 'カテゴリ別女性MC設定を再試行中' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'カテゴリ別女性MC設定を再試行中' }))
    expect(mockFetch).toHaveBeenCalledTimes(1)

    resolveFetch(sampleData)
    await waitFor(() => expect(screen.getByText('カテゴリ別女性MC設定')).toBeInTheDocument())
  })
})
