import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CategoryFemaleMcPanel from '../CategoryFemaleMcPanel'
import type { CategoryFemaleMcSettings } from '../../lib/admin-category-female-mc'

const mockSave = jest.fn()
jest.mock('../../lib/admin-category-female-mc', () => {
  const actual = jest.requireActual('../../lib/admin-category-female-mc')
  return {
    ...actual,
    saveCategoryFemaleMcClient: (...args: unknown[]) => mockSave(...args),
  }
})

const sampleData: CategoryFemaleMcSettings = {
  categories: ['テック・IT', '経済・ビジネス'],
  category_female_voices: { 'テック・IT': 'morigawa', '経済・ビジネス': null },
  default_voice: 'morigawa',
  voices: [
    {
      display_name: 'morigawa',
      value: 'morigawa',
      sample: {
        url: '/api/admin/settings/voices/categories/samples/morigawa',
        text: 'これはmorigawaのサンプル文です。',
        media_type: 'audio/wav',
        available: true,
      },
    },
    {
      display_name: 'female',
      value: 'female',
      sample: {
        url: '/api/admin/settings/voices/categories/samples/female',
        text: 'これはfemaleのサンプル文です。',
        media_type: 'audio/wav',
        available: false,
      },
    },
  ],
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}

beforeEach(() => {
  jest.clearAllMocks()
  window.HTMLMediaElement.prototype.play = jest.fn().mockResolvedValue(undefined)
  window.HTMLMediaElement.prototype.pause = jest.fn()
})

describe('CategoryFemaleMcPanel', () => {
  it('正常系：全カテゴリの現在割当・未設定・既定女性MCが表示される', () => {
    render(<CategoryFemaleMcPanel initialData={sampleData} />)
    expect(screen.getByText('カテゴリ別女性MC設定')).toBeInTheDocument()

    const techSelect = screen.getByLabelText('テック・ITの女性MC') as HTMLSelectElement
    expect(techSelect.value).toBe('morigawa')

    const bizSelect = screen.getByLabelText('経済・ビジネスの女性MC') as HTMLSelectElement
    expect(bizSelect.value).toBe('')
    expect(screen.getAllByText('未設定（既定: morigawa）').length).toBeGreaterThan(0)
  })

  it('未設定を選択できる', async () => {
    const user = userEvent.setup()
    render(<CategoryFemaleMcPanel initialData={sampleData} />)
    const techSelect = screen.getByLabelText('テック・ITの女性MC') as HTMLSelectElement
    await user.selectOptions(techSelect, '')
    expect(techSelect.value).toBe('')
  })

  it('サンプル未登録の候補は再生ボタンが無効化される', () => {
    render(<CategoryFemaleMcPanel initialData={sampleData} />)
    expect(screen.getByRole('button', { name: 'femaleのサンプルを再生' })).toBeDisabled()
  })

  it('再生・停止：候補を再生でき、別候補の再生時には先の音声が停止する', async () => {
    const user = userEvent.setup()
    render(<CategoryFemaleMcPanel initialData={sampleData} />)

    const morigawaButton = screen.getByRole('button', { name: 'morigawaのサンプルを再生' })
    await user.click(morigawaButton)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'morigawaのサンプルを停止' })).toBeInTheDocument()
    })
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'morigawaのサンプルを停止' }))
    expect(window.HTMLMediaElement.prototype.pause).toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'morigawaのサンプルを再生' })).toBeInTheDocument()
  })

  it('保存成功：保存後の反映説明が表示される', async () => {
    mockSave.mockResolvedValueOnce(sampleData)
    const user = userEvent.setup()
    render(<CategoryFemaleMcPanel initialData={sampleData} />)

    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(screen.getByText(/保存しました。保存後に開始する生成から反映されます。/)).toBeInTheDocument()
    })
    expect(mockSave).toHaveBeenCalledWith({ 'テック・IT': 'morigawa', '経済・ビジネス': null })
  })

  it('保存失敗：エラーメッセージが表示され値は保持される', async () => {
    mockSave.mockRejectedValueOnce(new Error('入力内容を確認してください。'))
    const user = userEvent.setup()
    render(<CategoryFemaleMcPanel initialData={sampleData} />)

    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(screen.getByText('入力内容を確認してください。')).toBeInTheDocument()
    })
    const techSelect = screen.getByLabelText('テック・ITの女性MC') as HTMLSelectElement
    expect(techSelect.value).toBe('morigawa')
  })

  it('再生失敗時は保存操作を妨げない', async () => {
    window.HTMLMediaElement.prototype.play = jest.fn().mockRejectedValue(new Error('failed'))
    mockSave.mockResolvedValueOnce(sampleData)
    const user = userEvent.setup()
    render(<CategoryFemaleMcPanel initialData={sampleData} />)

    await user.click(screen.getByRole('button', { name: 'morigawaのサンプルを再生' }))
    await waitFor(() => {
      expect(screen.getByText('サンプルを再生できませんでした')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(mockSave).toHaveBeenCalledTimes(1)
    })
  })

  it('二重送信防止：保存中は保存ボタンが無効化され1回しか呼ばれない', async () => {
    let resolveSave: (value: CategoryFemaleMcSettings) => void = () => {}
    mockSave.mockImplementationOnce(
      () => new Promise<CategoryFemaleMcSettings>((resolve) => { resolveSave = resolve }),
    )
    const user = userEvent.setup()
    render(<CategoryFemaleMcPanel initialData={clone(sampleData)} />)

    const button = screen.getByRole('button', { name: '保存' })
    await user.click(button)
    expect(screen.getByRole('button', { name: '保存中…' })).toBeDisabled()

    await user.click(button)
    expect(mockSave).toHaveBeenCalledTimes(1)

    resolveSave(sampleData)
    await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).not.toBeDisabled())
  })
})
