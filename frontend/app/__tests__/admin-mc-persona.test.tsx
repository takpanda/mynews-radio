import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminMcFormModal from '../components/AdminMcFormModal'
import type { Mc } from '../lib/admin-programs'

const mockReplaceMc = jest.fn()
const mockCreateMc = jest.fn()

jest.mock('../lib/admin-programs', () => ({
  ...jest.requireActual('../lib/admin-programs'),
  createMc: (...args: unknown[]) => mockCreateMc(...args),
  replaceMc: (...args: unknown[]) => mockReplaceMc(...args),
}))

const mc: Mc = {
  id: 'radio_male',
  name: '田村',
  role: 'メインMC',
  persona: '落ち着いた口調',
  voice_fishs2pro: null,
  voice_aivispeech: null,
  voice_voicevox: null,
  is_active: true,
  created_at: '',
  updated_at: '',
}

beforeEach(() => jest.clearAllMocks())

describe('AdminMcFormModal ペルソナ', () => {
  it('保存済みのペルソナを再表示し、編集した値を送信する', async () => {
    mockReplaceMc.mockResolvedValueOnce(mc)
    const user = userEvent.setup()
    render(<AdminMcFormModal mc={mc} onClose={jest.fn()} onSuccess={jest.fn()} />)

    const field = screen.getByLabelText(/ペルソナ/)
    expect(field).toHaveValue('落ち着いた口調')
    await user.clear(field)
    await user.type(field, '明るい口調')
    await user.click(screen.getByRole('button', { name: '保存する' }))

    expect(mockReplaceMc).toHaveBeenCalledWith('radio_male', expect.objectContaining({ persona: '明るい口調' }))
  })

  it('空にするとnullで送信する', async () => {
    mockReplaceMc.mockResolvedValueOnce(mc)
    const user = userEvent.setup()
    render(<AdminMcFormModal mc={mc} onClose={jest.fn()} onSuccess={jest.fn()} />)

    await user.clear(screen.getByLabelText(/ペルソナ/))
    await user.click(screen.getByRole('button', { name: '保存する' }))

    expect(mockReplaceMc).toHaveBeenCalledWith('radio_male', expect.objectContaining({ persona: null }))
  })

  it('4000文字を超える入力は保存せずエラーを表示する', async () => {
    const user = userEvent.setup()
    render(<AdminMcFormModal mc={{ ...mc, persona: 'あ'.repeat(4001) }} onClose={jest.fn()} onSuccess={jest.fn()} />)

    await user.click(screen.getByRole('button', { name: '保存する' }))

    expect(await screen.findByText('ペルソナは4000文字以内で入力してください')).toBeInTheDocument()
    expect(mockReplaceMc).not.toHaveBeenCalled()
  })
})
