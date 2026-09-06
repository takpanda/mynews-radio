import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FemaleMcCandidatesSection from '../FemaleMcCandidatesSection'
import type { FemaleMcCandidate } from '../../lib/admin-female-mc-candidates'

const mockFetch = jest.fn()
jest.mock('../../lib/admin-female-mc-candidates', () => {
  const actual = jest.requireActual('../../lib/admin-female-mc-candidates')
  return {
    ...actual,
    fetchFemaleMcCandidatesClient: (...args: unknown[]) => mockFetch(...args),
  }
})

const sampleData: FemaleMcCandidate[] = [
  {
    id: 1,
    voice_name: 'morigawa',
    display_name: 'もりかわ',
    sample_text: 'サンプル文',
    is_active: true,
    sample: {
      url: '/api/admin/settings/voices/categories/samples/morigawa',
      text: 'サンプル文',
      media_type: 'audio/wav',
      available: true,
    },
  },
]

beforeEach(() => {
  jest.clearAllMocks()
})

describe('FemaleMcCandidatesSection', () => {
  it('初期取得成功：女性MC候補マスタパネルが表示される', () => {
    render(<FemaleMcCandidatesSection initialData={sampleData} initialError={null} />)
    expect(screen.getByText('女性MC候補マスタ')).toBeInTheDocument()
  })

  it('初期取得失敗：エラーメッセージと再試行ボタンが表示される', () => {
    render(<FemaleMcCandidatesSection initialData={null} initialError="女性MC候補マスタを取得できませんでした。しばらく後でもう一度お試しください。" />)
    expect(screen.getByRole('alert')).toHaveTextContent('女性MC候補マスタを取得できませんでした。しばらく後でもう一度お試しください。')
    expect(screen.getByRole('button', { name: '女性MC候補マスタを再試行' })).toBeInTheDocument()
    expect(screen.queryByText('女性MC候補マスタ')).not.toBeInTheDocument()
  })

  it('再試行成功：取得できたデータでパネルが表示される', async () => {
    mockFetch.mockResolvedValueOnce(sampleData)
    const user = userEvent.setup()
    render(<FemaleMcCandidatesSection initialData={null} initialError="取得できませんでした" />)

    await user.click(screen.getByRole('button', { name: '女性MC候補マスタを再試行' }))

    await waitFor(() => {
      expect(screen.getByText('女性MC候補マスタ')).toBeInTheDocument()
    })
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })

  it('再試行失敗：エラーメッセージが更新され再試行ボタンは残る', async () => {
    mockFetch.mockRejectedValueOnce(new Error('保存できませんでした。しばらく後でもう一度お試しください。'))
    const user = userEvent.setup()
    render(<FemaleMcCandidatesSection initialData={null} initialError="取得できませんでした" />)

    await user.click(screen.getByRole('button', { name: '女性MC候補マスタを再試行' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('保存できませんでした。しばらく後でもう一度お試しください。')
    })
    expect(screen.getByRole('button', { name: '女性MC候補マスタを再試行' })).toBeInTheDocument()
  })

  it('再試行中は再試行ボタンが無効化され1回しか呼ばれない', async () => {
    let resolveFetch: (value: FemaleMcCandidate[]) => void = () => {}
    mockFetch.mockImplementationOnce(
      () => new Promise<FemaleMcCandidate[]>((resolve) => { resolveFetch = resolve }),
    )
    const user = userEvent.setup()
    render(<FemaleMcCandidatesSection initialData={null} initialError="取得できませんでした" />)

    const button = screen.getByRole('button', { name: '女性MC候補マスタを再試行' })
    await user.click(button)
    expect(screen.getByRole('button', { name: '女性MC候補マスタを再試行中' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: '女性MC候補マスタを再試行中' }))
    expect(mockFetch).toHaveBeenCalledTimes(1)

    resolveFetch(sampleData)
    await waitFor(() => expect(screen.getByText('女性MC候補マスタ')).toBeInTheDocument())
  })
})
