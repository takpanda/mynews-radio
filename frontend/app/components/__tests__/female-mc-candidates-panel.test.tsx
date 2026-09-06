import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FemaleMcCandidatesPanel from '../FemaleMcCandidatesPanel'
import type { FemaleMcCandidate } from '../../lib/admin-female-mc-candidates'

const mockUpdate = jest.fn()
const mockCreate = jest.fn()
jest.mock('../../lib/admin-female-mc-candidates', () => {
  const actual = jest.requireActual('../../lib/admin-female-mc-candidates')
  return {
    ...actual,
    updateFemaleMcCandidateClient: (...args: unknown[]) => mockUpdate(...args),
    createFemaleMcCandidateClient: (...args: unknown[]) => mockCreate(...args),
  }
})

const sampleCandidates: FemaleMcCandidate[] = [
  {
    id: 1,
    voice_name: 'morigawa',
    display_name: 'もりかわ',
    sample_text: 'これはもりかわのサンプル文です。',
    is_active: true,
    sample: {
      url: '/api/admin/settings/voices/categories/samples/morigawa',
      text: 'これはもりかわのサンプル文です。',
      media_type: 'audio/wav',
      available: true,
    },
  },
  {
    id: 2,
    voice_name: 'female',
    display_name: 'female',
    sample_text: 'これはfemaleのサンプル文です。',
    is_active: false,
    sample: {
      url: '/api/admin/settings/voices/categories/samples/female',
      text: 'これはfemaleのサンプル文です。',
      media_type: 'audio/wav',
      available: false,
    },
  },
]

beforeEach(() => {
  jest.clearAllMocks()
  window.HTMLMediaElement.prototype.play = jest.fn().mockResolvedValue(undefined)
  window.HTMLMediaElement.prototype.pause = jest.fn()
})

describe('FemaleMcCandidatesPanel', () => {
  it('正常系：候補一覧と有効/無効状態が表示される', () => {
    render(<FemaleMcCandidatesPanel initialData={sampleCandidates} />)
    expect(screen.getByText('女性MC候補マスタ')).toBeInTheDocument()
    expect(screen.getByText('もりかわ')).toBeInTheDocument()
    expect(screen.getAllByText('有効').length).toBeGreaterThan(0)
    expect(screen.getAllByText('無効').length).toBeGreaterThan(0)
  })

  it('候補が0件の場合は案内文を表示する', () => {
    render(<FemaleMcCandidatesPanel initialData={[]} />)
    expect(screen.getByText('候補がまだありません。「候補を追加」から追加してください。')).toBeInTheDocument()
  })

  it('サンプル未登録の候補は再生ボタンが無効化される', () => {
    render(<FemaleMcCandidatesPanel initialData={sampleCandidates} />)
    expect(screen.getByRole('button', { name: 'femaleのサンプルを再生' })).toBeDisabled()
  })

  it('再生・停止：候補を再生でき、再生ボタンが停止表示に切り替わる', async () => {
    const user = userEvent.setup()
    render(<FemaleMcCandidatesPanel initialData={sampleCandidates} />)

    await user.click(screen.getByRole('button', { name: 'もりかわのサンプルを再生' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'もりかわのサンプルを停止' })).toBeInTheDocument()
    })
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
  })

  it('有効/無効切り替え：スイッチ操作でupdateFemaleMcCandidateClientが呼ばれ表示が更新される', async () => {
    mockUpdate.mockResolvedValueOnce({ ...sampleCandidates[0], is_active: false })
    const user = userEvent.setup()
    render(<FemaleMcCandidatesPanel initialData={sampleCandidates} />)

    await user.click(screen.getByRole('switch', { name: 'もりかわを無効にする' }))

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith('morigawa', { is_active: false })
    })
  })

  it('有効/無効切り替え失敗時はエラーメッセージを表示する', async () => {
    mockUpdate.mockRejectedValueOnce(new Error('更新できませんでした'))
    const user = userEvent.setup()
    render(<FemaleMcCandidatesPanel initialData={sampleCandidates} />)

    await user.click(screen.getByRole('switch', { name: 'もりかわを無効にする' }))

    await waitFor(() => {
      expect(screen.getByText('更新できませんでした')).toBeInTheDocument()
    })
  })

  it('候補を追加：モーダルから追加すると一覧に反映される', async () => {
    mockCreate.mockResolvedValueOnce({
      id: 3,
      voice_name: 'newvoice',
      display_name: '新しい候補',
      sample_text: '',
      is_active: true,
      sample: {
        url: '/api/admin/settings/voices/categories/samples/newvoice',
        text: '',
        media_type: 'audio/wav',
        available: false,
      },
    })
    const user = userEvent.setup()
    render(<FemaleMcCandidatesPanel initialData={sampleCandidates} />)

    await user.click(screen.getByRole('button', { name: '候補を追加' }))
    await user.type(screen.getByPlaceholderText('例: morigawa'), 'newvoice')
    await user.type(screen.getByPlaceholderText('例: もりかわ'), '新しい候補')
    await user.click(screen.getByRole('button', { name: '追加する' }))

    await waitFor(() => {
      expect(screen.getByText('新しい候補')).toBeInTheDocument()
    })
    expect(mockCreate).toHaveBeenCalledWith({ voice_name: 'newvoice', display_name: '新しい候補' })
  })
})
